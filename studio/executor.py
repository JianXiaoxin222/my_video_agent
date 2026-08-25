from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from agents.common import PROJECT_ROOT
from agents.image.seedream_client import SeedreamClient
from agents.video.seedance_client import SeedanceClient
from agents.video.generate import build_content_blocks

from .compiler import _asset_list, _asset_value, preview_workflow
from .models import Workflow, infer_generation_mode
from .repository import StudioRepository
from .storage import StorageProvider, configured_provider, image_file_to_data_url
from .validation import topological_order
from .contracts import load_script_project, write_script_project
from .audit import record_studio_event


class WorkflowExecutor:
    def __init__(self, repository: StudioRepository | None = None, *, image_client=None, video_client=None, storage=None):
        self.repository = repository or StudioRepository()
        self.image_client = image_client
        self.video_client = video_client
        self.storage: StorageProvider = storage or configured_provider()
        self.events: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def _emit(self, run_id: str, status: str, message: str = "", **extra: Any) -> None:
        event = {"status": status, "message": message, **extra}
        record_studio_event("run_status", run_id=run_id, status=status, message=message, **extra)
        with self._lock:
            self.events.setdefault(run_id, []).append(event)

    @staticmethod
    def _artifact_url(path: Path) -> str:
        try:
            relative = path.resolve().relative_to((PROJECT_ROOT / "output").resolve())
            return "/outputs/" + relative.as_posix()
        except ValueError:
            return ""

    def _resolve_seedance_asset(self, value: Any) -> str:
        """Return a publicly reachable URL for a Seedance input asset."""
        raw = _asset_value(value)
        if not raw:
            raise ValueError("Seedance reference asset is empty")
        if raw.startswith(("http://", "https://")):
            return raw
        if raw.startswith("data:"):
            raise ValueError("Seedance reference assets must be public http(s) URLs; configure object storage and upload the local file")
        return self.storage.resolve(raw)

    def run(self, workflow: Workflow, *, run_id: str | None = None, node_ids: list[str] | None = None) -> str:
        run_id = run_id or uuid4().hex
        self.repository.save_run(run_id, workflow.id, "queued", {"events": []})
        thread = threading.Thread(target=self._run_sync, args=(workflow, run_id, node_ids), daemon=True)
        thread.start()
        return run_id

    def _run_sync(self, workflow: Workflow, run_id: str, node_ids: list[str] | None) -> None:
        try:
            self._emit(run_id, "running", "Workflow started")
            ordered = topological_order(workflow)
            selected = set(node_ids or ordered)
            if node_ids:
                # A single-node run still evaluates all of its upstream input
                # nodes so linked prompts/assets are available to the target.
                changed = True
                while changed:
                    changed = False
                    for edge in workflow.edges:
                        if edge.target in selected and edge.source not in selected:
                            selected.add(edge.source)
                            changed = True
            values: dict[str, Any] = {}
            safe_title = "".join(char if char.isalnum() or char in "._- " else "_" for char in workflow.title).strip() or "project"
            project_dir = PROJECT_ROOT / "output" / "projects" / safe_title
            image_client = self.image_client
            video_client = self.video_client
            for index, node_id in enumerate(ordered, start=1):
                if node_id not in selected:
                    continue
                node = workflow.node_map()[node_id]
                inputs = {}
                for edge in workflow.edges:
                    if edge.target == node_id and edge.source in values:
                        key = edge.target_handle or edge.source_handle or "input"
                        value = values[edge.source]
                        if key in {"image", "reference"} and key in inputs:
                            current = inputs[key] if isinstance(inputs[key], list) else [inputs[key]]
                            current.append(value)
                            inputs[key] = current
                        else:
                            inputs[key] = value
                data = node.data
                if node.type == "text_input":
                    values[node_id] = data.get("text", "")
                elif node.type in {"image_input", "video_input"}:
                    source = data.get("url") or data.get("path")
                    if not source:
                        values[node_id] = None
                    elif isinstance(source, str) and source.startswith("data:"):
                        values[node_id] = source
                    elif node.type == "image_input" and not str(source).startswith(("http://", "https://")):
                        # Keep the original path available: image generation
                        # can inline it for Seedream, while Seedance must send
                        # it through the configured public uploader.
                        values[node_id] = {"type": "image_asset", "path": str(source)}
                    else:
                        values[node_id] = self.storage.resolve(str(source))
                elif node.type == "image_generate":
                    image_client = image_client or SeedreamClient()
                    out_dir = project_dir / "character_images"
                    out_dir.mkdir(parents=True, exist_ok=True)
                    name = str(data.get("name", node_id))
                    safe_name = "".join(char if char.isalnum() or char in "._- " else "_" for char in name).strip() or node_id
                    out_path = out_dir / f"{safe_name}.jpg"
                    reference = inputs.get("reference", data.get("reference_image"))
                    references = reference if isinstance(reference, list) else [reference]
                    normalized_references: list[str] = []
                    for item in references:
                        if not item:
                            continue
                        if isinstance(item, dict):
                            # An upstream image-generation node emits a
                            # structured result. Pass its public URL when
                            # available, or inline the saved local artifact.
                            reference_path = item.get("path")
                            reference_url = item.get("url")
                            item = (reference_url if isinstance(reference_url, str) and reference_url.startswith(("http://", "https://", "data:")) else None) or (
                                image_file_to_data_url(reference_path)
                                if reference_path else None
                            )
                        elif item and not str(item).startswith(("http://", "https://", "data:")):
                            item = image_file_to_data_url(item)
                        if item:
                            normalized_references.append(str(item))
                    if len(normalized_references) > 1:
                        reference = normalized_references
                    else:
                        reference = normalized_references[0] if normalized_references else None
                    path, url = image_client.generate_image_url(prompt=inputs.get("prompt", data.get("prompt", "")), output_path=out_path,
                        reference_image=reference, model=data.get("model") or image_client.default_model, size=data.get("size"), watermark=data.get("watermark"))
                    public_url = url if isinstance(url, str) and url.startswith(("http://", "https://")) else None
                    if not public_url:
                        try:
                            public_url = self.storage.upload(path)
                        except (ValueError, RuntimeError, FileNotFoundError) as exc:
                            raise ValueError(
                                "Generated image has no public URL; configure VIDEO_AGENT_S3_* "
                                "to upload it before image-to-video generation"
                            ) from exc
                        if not isinstance(public_url, str) or not public_url.startswith(("http://", "https://")):
                            raise ValueError("Image storage provider must return a public http(s) URL")
                    values[node_id] = {"type": "image_result", "path": str(path), "url": public_url}
                elif node.type == "video_generate":
                    video_client = video_client or SeedanceClient()
                    out_dir = project_dir / "raw_videos"
                    out_dir.mkdir(parents=True, exist_ok=True)
                    image_values = data.get("image_urls") or inputs.get("image") or []
                    image_urls = [self._resolve_seedance_asset(item) for item in _asset_list(image_values)]
                    first_value = inputs.get("first_frame", data.get("first_frame") or data.get("first_frame_url"))
                    last_value = inputs.get("last_frame", data.get("last_frame") or data.get("last_frame_url"))
                    first_frame = self._resolve_seedance_asset(first_value) if first_value else None
                    last_frame = self._resolve_seedance_asset(last_value) if last_value else None
                    video_value = inputs.get("video", data.get("video_url"))
                    video_url = self._resolve_seedance_asset(video_value) if video_value else None
                    audio_value = data.get("audio_url")
                    audio_url = self._resolve_seedance_asset(audio_value) if audio_value else None
                    content = build_content_blocks(inputs.get("prompt", data.get("prompt", "")), image_urls=image_urls, first_frame_url=first_frame, last_frame_url=last_frame, video_url=video_url, audio_url=audio_url)
                    output_name = Path(str(data.get("output_name", f"{node_id}.mp4"))).name
                    if not output_name.lower().endswith(".mp4"):
                        output_name += ".mp4"
                    out_path = out_dir / output_name
                    path = video_client.generate(content=content, output_path=out_path, model=data.get("model") or video_client.default_model, ratio=data.get("ratio"), duration=data.get("duration"), watermark=data.get("watermark"), generate_audio=data.get("generate_audio"), resolution=data.get("resolution"), return_last_frame=data.get("return_last_frame"))
                    values[node_id] = {"type": "video_result", "path": str(path), "url": self._artifact_url(Path(path))}
                elif node.type == "output":
                    values[node_id] = inputs.get("input")
                elif node.type == "script_project":
                    operation = data.get("operation", "import")
                    source_dir = data.get("project_dir")
                    if operation == "import" and source_dir:
                        values[node_id] = load_script_project(source_dir)
                    elif operation == "export":
                        values[node_id] = write_script_project(source_dir or project_dir, inputs.get("project", data.get("payload", {})))
                self._emit(run_id, "running", f"Completed {node_id}", node_id=node_id, progress=round(index / max(len(ordered), 1) * 100))
            self._emit(run_id, "succeeded", "Workflow completed", results=values)
            self.repository.save_run(run_id, workflow.id, "succeeded", {"events": self.events.get(run_id, []), "results": values})
        except Exception as exc:
            self._emit(run_id, "failed", str(exc))
            self.repository.save_run(run_id, workflow.id, "failed", {"events": self.events.get(run_id, []), "error": str(exc)})
