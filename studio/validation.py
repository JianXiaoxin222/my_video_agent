from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .models import NODE_TYPES, Workflow


PORT_TYPES: dict[str, dict[str, str]] = {
    "text_input": {"text": "text"},
    "image_input": {"image": "image"},
    "video_input": {"video": "video"},
    "image_generate": {"prompt": "text", "reference": "image", "image": "image_result"},
    "video_generate": {
        "prompt": "text",
        "image": "image_list",
        "first_frame": "image",
        "last_frame": "image",
        "video": "video",
        "video_result": "video_result",
    },
    "script_project": {"project": "script_project"},
    "output": {"input": "any"},
}


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "errors": self.errors, "warnings": self.warnings}


def _is_public_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_inline_image(value: str) -> bool:
    """Seedream accepts an image data URL for local image-to-image input."""
    return value.startswith("data:image/") and ";base64," in value


def _value_for_handle(node: Any, handle: str | None) -> str | None:
    if not handle:
        return None
    return PORT_TYPES.get(node.type, {}).get(handle)


def validate_workflow(workflow: Workflow, *, require_public_assets: bool = False) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    nodes = workflow.node_map()
    outgoing_sources = {edge.source for edge in workflow.edges}
    connected_inputs = {(edge.target, edge.target_handle) for edge in workflow.edges}

    if workflow.schema_version != 1:
        errors.append(f"Unsupported schema_version: {workflow.schema_version}")
    if not workflow.title.strip():
        errors.append("Workflow title is required")
    if len(nodes) != len(workflow.nodes):
        errors.append("Node ids must be unique")

    for node in workflow.nodes:
        if node.type not in NODE_TYPES:
            errors.append(f"{node.id}: unknown node type '{node.type}'")
            continue
        if node.type == "image_generate":
            if node.data.get("reference_image") and (node.id, "reference") not in connected_inputs:
                warnings.append(f"{node.id}: reference_image is legacy; connect an image input to make the dependency visible")
        if node.type == "video_generate":
            duration = node.data.get("duration")
            if duration is not None and (not isinstance(duration, (int, float)) or not 4 <= int(duration) <= 15):
                errors.append(f"{node.id}: Seedance duration must be between 4 and 15 seconds")
            ratio = node.data.get("ratio")
            if ratio is not None and ratio not in {"21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}:
                errors.append(f"{node.id}: unsupported Seedance ratio '{ratio}'")
            resolution = node.data.get("resolution")
            if resolution is not None and resolution not in {"480p", "720p", "1080p", "4k"}:
                errors.append(f"{node.id}: unsupported Seedance resolution '{resolution}'")
            if node.data.get("image_urls") and (node.id, "image") not in connected_inputs:
                warnings.append(f"{node.id}: image_urls is legacy; connect image nodes to make the dependency visible")
            if node.data.get("video_url") and (node.id, "video") not in connected_inputs:
                warnings.append(f"{node.id}: video_url is legacy; connect a video node to make the dependency visible")
            if node.data.get("first_frame") and (node.id, "first_frame") not in connected_inputs:
                warnings.append(f"{node.id}: first_frame is legacy; connect an image node to make the dependency visible")
            if node.data.get("last_frame") and (node.id, "last_frame") not in connected_inputs:
                warnings.append(f"{node.id}: last_frame is legacy; connect an image node to make the dependency visible")
            if require_public_assets:
                direct_assets: list[tuple[str, Any]] = [
                    ("image_urls", node.data.get("image_urls")),
                    ("first_frame", node.data.get("first_frame") or node.data.get("first_frame_url")),
                    ("last_frame", node.data.get("last_frame") or node.data.get("last_frame_url")),
                    ("video_url", node.data.get("video_url")),
                    ("audio_url", node.data.get("audio_url")),
                ]
                for field_name, raw_value in direct_assets:
                    if raw_value is None:
                        continue
                    values = raw_value if isinstance(raw_value, list) else [raw_value]
                    for value in values:
                        if isinstance(value, dict):
                            value = value.get("url") or value.get("path")
                        if value and not _is_public_url(str(value)):
                            errors.append(f"{node.id}.{field_name}: Seedance assets must be public http(s) URLs")
        if node.type in {"image_input", "video_input"}:
            source = node.data.get("url") or node.data.get("path")
            if not source and node.id in outgoing_sources:
                errors.append(f"{node.id}: asset URL or local path is required")
            elif source and require_public_assets:
                source = str(source)
                if _is_public_url(source):
                    pass
                elif node.type == "image_input" and _is_inline_image(source):
                    # Inline image data is valid for Seedream image-to-image.
                    # It is not a valid Seedance reference asset, which must
                    # remain a public URL.
                    video_targets = {edge.target for edge in workflow.edges if edge.source == node.id and edge.target in nodes}
                    if any(nodes[target].type == "video_generate" for target in video_targets):
                        errors.append(f"{node.id}: inline image data cannot be sent to Seedance; upload it and use a public URL")
                else:
                    errors.append(f"{node.id}: asset must be a public http(s) URL or uploaded first")

    indegree = {node_id: 0 for node_id in nodes}
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for edge in workflow.edges:
        if edge.source not in nodes or edge.target not in nodes:
            errors.append(f"{edge.id}: source or target node does not exist")
            continue
        source_type = _value_for_handle(nodes[edge.source], edge.source_handle)
        target_type = _value_for_handle(nodes[edge.target], edge.target_handle)
        compatible = source_type == target_type or (source_type in {"image", "image_result"} and target_type == "image_list") or (source_type == "image_result" and target_type == "image")
        if source_type and target_type and target_type != "any" and not compatible:
            errors.append(f"{edge.id}: incompatible ports {source_type} -> {target_type}")
        adjacency[edge.source].append(edge.target)
        indegree[edge.target] += 1

    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited = 0
    while queue:
        current = queue.pop(0)
        visited += 1
        for target in adjacency[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(nodes):
        errors.append("Workflow must be a DAG; a cycle was detected")

    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)


def topological_order(workflow: Workflow) -> list[str]:
    result = validate_workflow(workflow)
    if not result.valid:
        raise ValueError("Cannot order invalid workflow: " + "; ".join(result.errors))
    nodes = workflow.node_map()
    incoming = {node_id: 0 for node_id in nodes}
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for edge in workflow.edges:
        adjacency[edge.source].append(edge.target)
        incoming[edge.target] += 1
    queue = [node_id for node_id, count in incoming.items() if count == 0]
    ordered: list[str] = []
    while queue:
        current = queue.pop(0)
        ordered.append(current)
        for target in adjacency[current]:
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    return ordered
