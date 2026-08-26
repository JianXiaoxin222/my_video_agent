from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from agents.common import PROJECT_ROOT
from agents.common.log_writer import record_error
from agents.image.seedream_client import SeedreamClient
from agents.video.seedance_client import SeedanceClient
from .compiler import _asset_value, _connected_values, preview_workflow
from .media import iter_video_media, media_content_blocks
from .models import Workflow
from .repository import StudioRepository
from .storage import StorageProvider, configured_provider, image_file_to_data_url
from .validation import topological_order
from .projects import project_directory
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

    @staticmethod
    def _pass_seedance_image(value: Any) -> str:
        """Pass an image reference through without URL pre-validation.

        Seedance records and validates image references at the provider boundary.
        Keeping the original value here allows its response (for example, an
        inline-data rejection) to be captured in the normal request/error logs.
        """
        raw = _asset_value(value)
        if not raw:
            raise ValueError("Seedance image reference is empty")
        return raw

    @staticmethod
    def _unique_image_output_path(project_dir: Path) -> Path:
        output_dir = project_dir / "character_images"
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().strftime("%Y_%m_%d_%H_%M_%S_%f")[:-3]
        candidate = output_dir / f"generate_image_{stamp}.jpg"
        suffix = 1
        while candidate.exists():
            candidate = output_dir / f"generate_image_{stamp}_{suffix:03d}.jpg"
            suffix += 1
        return candidate
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
            project_dir = project_directory(workflow.project_name)
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
                elif node.type in {"image_input", "video_input", "audio_input", "fetch"}:
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
                    out_path = self._unique_image_output_path(project_dir)
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

                    def resolve_media(kind: str, value: Any) -> str:
                        return self._pass_seedance_image(value) if kind == "image" else self._resolve_seedance_asset(value)

                    media_items = list(iter_video_media(workflow, node_id, values, data, resolve=resolve_media))
                    content = ([{"type": "text", "text": inputs.get("prompt", data.get("prompt", ""))}] if inputs.get("prompt", data.get("prompt", "")) else []) + media_content_blocks(media_items)
                    output_name = Path(str(data.get("output_name", f"{node_id}.mp4"))).name
                    if not output_name.lower().endswith(".mp4"):
                        output_name += ".mp4"
                    out_path = out_dir / output_name
                    path = video_client.generate(content=content, output_path=out_path, model=data.get("model") or video_client.default_model, ratio=data.get("ratio"), duration=data.get("duration"), watermark=data.get("watermark"), generate_audio=data.get("generate_audio"), resolution=data.get("resolution"), return_last_frame=data.get("return_last_frame"))
                    values[node_id] = {"type": "video_result", "path": str(path), "url": self._artifact_url(Path(path)), "references": media_items}
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
            record_error("Studio workflow execution failed", exc=exc, context={"run_id": run_id, "workflow_id": workflow.id})
            self._emit(run_id, "failed", str(exc))
            self.repository.save_run(run_id, workflow.id, "failed", {"events": self.events.get(run_id, []), "error": str(exc)})
