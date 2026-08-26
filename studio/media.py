from __future__ import annotations

from typing import Any, Callable, Iterator

from .models import Workflow


VIDEO_REFERENCE_HANDLES = {"references", "image", "video", "audio", "media"}
FRAME_HANDLES = {"first_frame", "last_frame"}


def canonical_input_handle(node_type: str, handle: str | None) -> str:
    """Normalize legacy video handles to the multi-value references input."""
    value = handle or "input"
    if node_type == "video_generate" and value in VIDEO_REFERENCE_HANDLES:
        return "references"
    return value


def is_video_media_handle(node_type: str, handle: str | None) -> bool:
    return node_type == "video_generate" and (handle or "") in (VIDEO_REFERENCE_HANDLES | FRAME_HANDLES)


def _type_from_value(value: Any) -> str | None:
    if isinstance(value, dict):
        value_type = str(value.get("type") or "")
        if "image" in value_type:
            return "image"
        if "video" in value_type:
            return "video"
        if "audio" in value_type:
            return "audio"
    return None


def media_kind(source_type: str, source_handle: str | None, value: Any) -> str | None:
    """Infer the provider media kind without depending on a node's mode field."""
    from_value = _type_from_value(value)
    if from_value:
        return from_value
    handle = (source_handle or "").lower()
    if "audio" in handle or source_type == "audio_input":
        return "audio"
    if "video" in handle or source_type in {"video_input", "video_generate"}:
        return "video"
    if "image" in handle or source_type in {"image_input", "image_generate", "fetch"}:
        return "image"
    return None


def _asset_value(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, dict):
        url = value.get("url")
        if isinstance(url, str) and url:
            return url
        path = value.get("path")
        return str(path) if path else None
    return str(value)


def iter_video_media(
    workflow: Workflow,
    node_id: str,
    values: dict[str, Any],
    data: dict[str, Any],
    resolve: Callable[[str, Any], str | None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield D's media references in persisted edge order.

    Legacy direct fields remain supported. They are appended only when their
    corresponding media kind is not already supplied by a connected edge.
    """
    nodes = workflow.node_map()
    connected_kinds: set[str] = set()
    connected_roles: set[str] = set()
    connected = False
    for edge in workflow.edges:
        if edge.target != node_id or edge.source not in values:
            continue
        target_handle = edge.target_handle or edge.source_handle
        if target_handle not in (VIDEO_REFERENCE_HANDLES | FRAME_HANDLES):
            continue
        source = nodes.get(edge.source)
        if not source:
            continue
        value = values.get(edge.source)
        kind = media_kind(source.type, edge.source_handle, value)
        if not kind:
            continue
        connected = True
        connected_kinds.add(kind)
        resolved = resolve(kind, value) if resolve else _asset_value(value)
        if not resolved:
            continue
        role = "reference_" + kind
        if target_handle in {"first_frame", "last_frame"}:
            role = target_handle
        connected_roles.add(role)
        yield {"kind": kind, "url": resolved, "role": role, "edge_id": edge.id}

    # Direct fields are legacy fallbacks, but remain useful for hand-authored
    # payloads and for mixed requests that add an audio/video reference.
    if "first_frame" not in connected_roles and (data.get("first_frame") or data.get("first_frame_url")):
        value = data.get("first_frame") or data.get("first_frame_url")
        resolved = resolve("image", value) if resolve else _asset_value(value)
        if resolved:
            yield {"kind": "image", "url": resolved, "role": "first_frame", "edge_id": None}
    if "last_frame" not in connected_roles and (data.get("last_frame") or data.get("last_frame_url")):
        value = data.get("last_frame") or data.get("last_frame_url")
        resolved = resolve("image", value) if resolve else _asset_value(value)
        if resolved:
            yield {"kind": "image", "url": resolved, "role": "last_frame", "edge_id": None}
    if "image" not in connected_kinds:
        image_values = data.get("image_urls")
        if image_values:
            items = image_values if isinstance(image_values, list) else [image_values]
            for item in items:
                resolved = resolve("image", item) if resolve else _asset_value(item)
                if resolved:
                    yield {"kind": "image", "url": resolved, "role": "reference_image", "edge_id": None}
    if "video" not in connected_kinds and data.get("video_url"):
        resolved = resolve("video", data.get("video_url")) if resolve else _asset_value(data.get("video_url"))
        if resolved:
            yield {"kind": "video", "url": resolved, "role": "reference_video", "edge_id": None}
    if "audio" not in connected_kinds and data.get("audio_url"):
        resolved = resolve("audio", data.get("audio_url")) if resolve else _asset_value(data.get("audio_url"))
        if resolved:
            yield {"kind": "audio", "url": resolved, "role": "reference_audio", "edge_id": None}


def media_content_blocks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert ordered internal media references to Ark content blocks."""
    blocks: list[dict[str, Any]] = []
    for item in items:
        url = item.get("url")
        if not url:
            continue
        kind = item.get("kind")
        role = item.get("role") or f"reference_{kind}"
        if kind == "image":
            blocks.append({"type": "image_url", "image_url": {"url": url}, "role": role})
        elif kind == "video":
            blocks.append({"type": "video_url", "video_url": {"url": url}, "role": role})
        elif kind == "audio":
            blocks.append({"type": "audio_url", "audio_url": {"url": url}, "role": role})
    return blocks
