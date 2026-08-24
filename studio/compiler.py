from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.video.generate import build_content_blocks

from .models import Workflow, infer_generation_mode
from .storage import StorageProvider, configured_provider, image_file_to_data_url
from .contracts import load_script_project
from .validation import topological_order


def _asset_value(item: Any) -> str | None:
    """Extract a URL/path from a connected asset or generation result."""
    if not item:
        return None
    if isinstance(item, dict):
        url = item.get("url")
        if isinstance(url, str) and (url.startswith(("http://", "https://", "data:"))):
            return url
        return item.get("path") or url
    return str(item)


def _asset_list(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [asset for item in items if (asset := _asset_value(item))]


def _connected_values(workflow: Workflow, node_id: str, values: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for edge in workflow.edges:
        if edge.target != node_id or edge.source not in values:
            continue
        key = edge.target_handle or edge.source_handle or "input"
        value = values[edge.source]
        # Image-generation references use the ``reference`` handle while
        # video inputs use ``image``. Both handles are multi-valued and must
        # preserve the edge order for Seedream/Seedance indexing.
        if key in {"image", "reference"} and key in result:
            current = result[key] if isinstance(result[key], list) else [result[key]]
            current.append(value)
            result[key] = current
        else:
            result[key] = value
    return result


def preview_workflow(workflow: Workflow, *, storage: StorageProvider | None = None) -> dict[str, Any]:
    storage = storage or configured_provider()
    ordered = topological_order(workflow)
    values: dict[str, Any] = {}
    payloads: list[dict[str, Any]] = []
    for node_id in ordered:
        node = workflow.node_map()[node_id]
        inputs = _connected_values(workflow, node_id, values)
        data = node.data
        if node.type == "text_input":
            values[node_id] = data.get("text", "")
        elif node.type in {"image_input", "video_input"}:
            source = data.get("url") or data.get("path")
            if not source:
                values[node_id] = None
            elif str(source).startswith("data:") or str(source).startswith(("http://", "https://")):
                values[node_id] = str(source)
            elif node.type == "image_input":
                values[node_id] = image_file_to_data_url(source)
            else:
                values[node_id] = str(source)
        elif node.type == "image_generate":
            prompt = inputs.get("prompt", data.get("prompt", ""))
            reference = inputs.get("reference", data.get("reference_image"))
            raw_references = reference if isinstance(reference, list) else [reference]
            normalized_references: list[str] = []
            for item in raw_references:
                if not item:
                    continue
                if isinstance(item, dict):
                    item_url = item.get("url")
                    item = (item_url if isinstance(item_url, str) and item_url.startswith(("http://", "https://", "data:")) else None) or (
                        image_file_to_data_url(item["path"])
                        if item.get("path") else None
                    )
                if item:
                    normalized_references.append(str(item))
            if len(normalized_references) > 1:
                reference = normalized_references
            else:
                reference = normalized_references[0] if normalized_references else None
            payload = {"kind": "image", "mode": infer_generation_mode(workflow, node_id) or ("image_to_image" if reference else "text_to_image"), "prompt": prompt, "image": reference,
                       "model": data.get("model") or "doubao-seedream-5-0-pro-260628", "size": data.get("size", "1920x1080"), "watermark": bool(data.get("watermark", False))}
            payloads.append(payload)
            values[node_id] = {"type": "image_result", "preview": payload}
        elif node.type == "video_generate":
            prompt = inputs.get("prompt", data.get("prompt", ""))
            image_urls = data.get("image_urls") or inputs.get("image") or []
            # Keep a single generated image result intact as one item.  Without
            # this normalization a result dict is iterated by key (``type``,
            # ``path``, ``url``), producing an invalid preview payload.
            image_urls = _asset_list(image_urls)
            first_frame = _asset_value(inputs.get("first_frame", data.get("first_frame") or data.get("first_frame_url")))
            last_frame = _asset_value(inputs.get("last_frame", data.get("last_frame") or data.get("last_frame_url")))
            video_url = _asset_value(inputs.get("video", data.get("video_url")))
            audio_url = _asset_value(data.get("audio_url"))
            payload = {"kind": "video", "mode": infer_generation_mode(workflow, node_id) or ("video_to_video" if video_url else ("image_to_video" if (image_urls or first_frame or last_frame) else "text_to_video")),
                       "prompt": prompt, "content": build_content_blocks(prompt, image_urls=image_urls, first_frame_url=first_frame, last_frame_url=last_frame, video_url=video_url, audio_url=audio_url),
                       "model": data.get("model") or "doubao-seedance-2-0-mini-260615", "ratio": data.get("ratio", "16:9"), "duration": int(data.get("duration", 5)),
                       "watermark": bool(data.get("watermark", False)), "generate_audio": bool(data.get("generate_audio", True))}
            payload["resolution"] = data.get("resolution", "480p")
            if "return_last_frame" in data:
                payload["return_last_frame"] = bool(data["return_last_frame"])
            payloads.append(payload)
            values[node_id] = {"type": "video_result", "preview": payload}
        elif node.type == "output":
            values[node_id] = inputs.get("input")
        elif node.type == "script_project":
            project_dir = data.get("project_dir")
            values[node_id] = load_script_project(project_dir) if project_dir else {"project_dir": None}
    return {"workflow_id": workflow.id, "payloads": payloads, "estimated_cost": sum(p.get("duration", 0) for p in payloads)}
