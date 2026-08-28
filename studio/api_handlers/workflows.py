from __future__ import annotations

import secrets
from typing import Any

from fastapi import HTTPException

from ..audit import record_studio_event
from ..compiler import preview_workflow
from ..models import Workflow
from ..projects import project_directory
from ..validation import validate_workflow
from .context import ApiContext


def _ensure_project(workflow: Workflow) -> None:
    try:
        project_directory(workflow.project_name)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


def create_workflow(ctx: ApiContext, payload: dict[str, Any]) -> dict[str, Any]:
    workflow = Workflow.from_dict(payload)
    _ensure_project(workflow)
    ctx.repository.save_workflow(workflow)
    return workflow.to_dict()


def get_workflow(ctx: ApiContext, workflow_id: str) -> dict[str, Any]:
    workflow = ctx.repository.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    return workflow.to_dict()


def update_workflow(ctx: ApiContext, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload["id"] = workflow_id
    workflow = Workflow.from_dict(payload)
    _ensure_project(workflow)
    ctx.repository.save_workflow(workflow)
    return workflow.to_dict()


def _load_workflow(ctx: ApiContext, workflow_id: str, payload: dict[str, Any] | None) -> Workflow:
    workflow = Workflow.from_dict(payload) if payload else ctx.repository.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    _ensure_project(workflow)
    return workflow


def validate(ctx: ApiContext, workflow_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    workflow = _load_workflow(ctx, workflow_id, payload)
    validation = validate_workflow(workflow, require_public_assets=True)
    if not validation.valid:
        record_studio_event("workflow_validation_error", workflow_id=workflow_id, errors=validation.errors, error_details=validation.error_details)
    return validation.as_dict()


def preview(ctx: ApiContext, workflow_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    workflow = _load_workflow(ctx, workflow_id, payload)
    validation = validate_workflow(workflow, require_public_assets=True)
    result = validation.as_dict()
    if not result["valid"]:
        record_studio_event("workflow_validation_error", workflow_id=workflow_id, errors=validation.errors, error_details=validation.error_details)
        return {"valid": False, **result}
    token = secrets.token_urlsafe(24)
    ctx.confirmation_tokens[workflow_id] = token
    return {"valid": True, "confirmation_token": token, **preview_workflow(workflow)}


def run(ctx: ApiContext, workflow_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    workflow_payload = payload.get("workflow") if payload and payload.get("workflow") else (payload if payload and payload.get("nodes") else None)
    workflow = Workflow.from_dict(workflow_payload) if workflow_payload else ctx.repository.get_workflow(workflow_id)
    if not workflow:
        record_studio_event("run_rejected", workflow_id=workflow_id, reason="workflow_not_found")
        raise HTTPException(404, "Workflow not found")
    if not payload or payload.get("confirmed") is not True or payload.get("confirmation_token") != ctx.confirmation_tokens.get(workflow_id):
        record_studio_event("run_rejected", workflow_id=workflow_id, reason="confirmation_required")
        raise HTTPException(409, "Explicit confirmation is required before API execution")
    _ensure_project(workflow)
    validation = validate_workflow(workflow, require_public_assets=True)
    if not validation.valid:
        record_studio_event("run_rejected", workflow_id=workflow_id, reason="validation", errors=validation.errors, error_details=validation.error_details)
        raise HTTPException(422, validation.as_dict())
    ctx.confirmation_tokens.pop(workflow_id, None)
    run_id = ctx.executor.run(workflow, node_ids=payload.get("node_ids"))
    return {"run_id": run_id, "status": "queued"}


def generate_node(ctx: ApiContext, workflow_id: str, node_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Confirm and execute exactly one generation node plus its ancestors."""
    workflow = Workflow.from_dict(payload.get("workflow")) if payload and payload.get("workflow") else ctx.repository.get_workflow(workflow_id)
    if not workflow or node_id not in workflow.node_map():
        raise HTTPException(404, "Workflow or node not found")
    if not payload or payload.get("confirmed") is not True:
        raise HTTPException(409, "Click the node's confirm generation button to start the API request")
    node = workflow.node_map()[node_id]
    if node.type not in {"image_generate", "video_generate"}:
        raise HTTPException(422, "Only image_generate and video_generate nodes can be run individually")
    _ensure_project(workflow)
    validation = validate_workflow(workflow, require_public_assets=True)
    if not validation.valid:
        record_studio_event("run_rejected", workflow_id=workflow_id, node_id=node_id, errors=validation.errors, error_details=validation.error_details)
        raise HTTPException(422, validation.as_dict())
    record_studio_event("run_requested", workflow_id=workflow_id, node_id=node_id, model=node.data.get("model"))
    run_id = ctx.executor.run(workflow, node_ids=[node_id])
    return {"run_id": run_id, "status": "queued", "node_id": node_id}

