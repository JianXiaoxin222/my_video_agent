from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


NODE_TYPES = {
    "text_input",
    "image_input",
    "video_input",
    "image_generate",
    "video_generate",
    "script_project",
    "output",
}

IMAGE_MODES = {"text_to_image", "image_to_image"}
VIDEO_MODES = {"text_to_video", "image_to_video", "video_to_video", "first_last_frame_to_video"}


def infer_generation_mode(workflow: "Workflow", node_id: str) -> str | None:
    """Infer a generation mode from connected upstream media nodes.

    Explicit mode fields are intentionally ignored for graph-authored
    workflows: media links are the source of truth. Legacy payload fields are
    still accepted by callers as a fallback when no link exists.
    """
    nodes = workflow.node_map()
    target = nodes.get(node_id)
    if not target:
        return None
    upstream_types = {nodes[edge.source].type for edge in workflow.edges if edge.target == node_id and edge.source in nodes}
    if target.type == "image_generate":
        return "image_to_image" if upstream_types & {"image_input", "image_generate"} else "text_to_image"
    if target.type == "video_generate":
        handles = {edge.target_handle or edge.source_handle for edge in workflow.edges if edge.target == node_id}
        if "first_frame" in handles or "last_frame" in handles:
            return "first_last_frame_to_video"
        if upstream_types & {"video_input", "video_generate"}:
            return "video_to_video"
        if upstream_types & {"image_input", "image_generate"}:
            return "image_to_video"
        return "text_to_video"
    return None


@dataclass
class WorkflowNode:
    id: str
    type: str
    position: dict[str, float] = field(default_factory=lambda: {"x": 0, "y": 0})
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkflowNode":
        return cls(
            id=str(value.get("id") or uuid4().hex),
            type=str(value.get("type") or ""),
            position=dict(value.get("position") or {"x": 0, "y": 0}),
            data=dict(value.get("data") or {}),
        )


@dataclass
class WorkflowEdge:
    id: str
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkflowEdge":
        return cls(
            id=str(value.get("id") or uuid4().hex),
            source=str(value.get("source") or ""),
            target=str(value.get("target") or ""),
            source_handle=value.get("source_handle", value.get("sourceHandle")),
            target_handle=value.get("target_handle", value.get("targetHandle")),
        )


@dataclass
class Workflow:
    id: str = field(default_factory=lambda: uuid4().hex)
    title: str = "Untitled workflow"
    project_name: str = "default"
    schema_version: int = 1
    nodes: list[WorkflowNode] = field(default_factory=list)
    edges: list[WorkflowEdge] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Workflow":
        return cls(
            id=str(value.get("id") or uuid4().hex),
            title=str(value.get("title") or "Untitled workflow"),
            project_name=str(value.get("project_name") or "default"),
            schema_version=int(value.get("schema_version", 1)),
            nodes=[WorkflowNode.from_dict(n) for n in value.get("nodes", [])],
            edges=[WorkflowEdge.from_dict(e) for e in value.get("edges", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def node_map(self) -> dict[str, WorkflowNode]:
        return {node.id: node for node in self.nodes}
