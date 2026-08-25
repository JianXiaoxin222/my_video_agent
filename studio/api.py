import asyncio
import json
import secrets
from pathlib import Path
from typing import Any

from .compiler import preview_workflow
from .executor import WorkflowExecutor
from .models import Workflow
from .repository import StudioRepository
from .storage import configured_provider, image_bytes_to_data_url
from .validation import validate_workflow
from agents.common import PROJECT_ROOT
from agents.common.config_loader import load_config_or_default
from .audit import record_studio_event


def create_app():
    try:
        from fastapi import FastAPI, HTTPException, UploadFile, File
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import StreamingResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError("Install FastAPI and Uvicorn with: pip install -r requirements.txt") from exc

    app = FastAPI(title="Video Agent Studio", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])
    app.mount("/outputs", StaticFiles(directory=PROJECT_ROOT / "output"), name="outputs")
    repository = StudioRepository()
    executor = WorkflowExecutor(repository)
    confirmation_tokens: dict[str, str] = {}

    @app.get("/api/health")
    def health():
        return {"ok": True, "service": "video-agent-studio"}

    @app.post("/api/client-errors")
    def client_error(payload: dict[str, Any]):
        """Record a UI-visible error in the same Studio audit log."""
        record_studio_event(
            "client_error",
            source="studio-ui",
            action=str(payload.get("action") or "unknown"),
            message=str(payload.get("message") or "Unknown UI error"),
            status_code=payload.get("status_code"),
        )
        return {"ok": True}

    @app.get("/api/models")
    def models():
        image_cfg = load_config_or_default("config/seedream.yaml", default={}).get("seedream", {})
        video_cfg = load_config_or_default("config/seedance.yaml", default={}).get("seedance", {})
        image_models = image_cfg.get("models", {})
        video_models = video_cfg.get("models", {})
        return {
            "image": {"default": image_models.get("default", "doubao-seedream-5-0-pro-260628"), "options": [image_models.get("default", "doubao-seedream-5-0-pro-260628")]},
            "video": {"default": video_models.get("default", "doubao-seedance-2-0-mini-260615"), "options": [video_models.get("default", "doubao-seedance-2-0-mini-260615"), video_models.get("pro", "doubao-seedance-2-0-260128")]},
        }

    @app.get("/api/logs/runs")
    def run_logs(limit: int = 100):
        path = PROJECT_ROOT / "logs" / "studio_runs.jsonl"
        if not path.exists():
            return {"entries": []}
        lines = path.read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 500)):]
        entries = []
        for line in lines:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append({"raw": line})
        return {"entries": entries}

    @app.post("/api/workflows")
    def create_workflow(payload: dict[str, Any]):
        workflow = Workflow.from_dict(payload)
        repository.save_workflow(workflow)
        return workflow.to_dict()

    @app.get("/api/workflows/{workflow_id}")
    def get_workflow(workflow_id: str):
        workflow = repository.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(404, "Workflow not found")
        return workflow.to_dict()

    @app.put("/api/workflows/{workflow_id}")
    def update_workflow(workflow_id: str, payload: dict[str, Any]):
        payload["id"] = workflow_id
        workflow = Workflow.from_dict(payload)
        repository.save_workflow(workflow)
        return workflow.to_dict()

    @app.post("/api/workflows/{workflow_id}/validate")
    def validate(workflow_id: str, payload: dict[str, Any] | None = None):
        workflow = Workflow.from_dict(payload) if payload else repository.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(404, "Workflow not found")
        return validate_workflow(workflow, require_public_assets=False).as_dict()

    @app.post("/api/workflows/{workflow_id}/preview")
    def preview(workflow_id: str, payload: dict[str, Any] | None = None):
        workflow = Workflow.from_dict(payload) if payload else repository.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(404, "Workflow not found")
        result = validate_workflow(workflow).as_dict()
        if not result["valid"]:
            return {"valid": False, **result}
        token = secrets.token_urlsafe(24)
        confirmation_tokens[workflow_id] = token
        return {"valid": True, "confirmation_token": token, **preview_workflow(workflow)}

    @app.post("/api/workflows/{workflow_id}/runs")
    def run(workflow_id: str, payload: dict[str, Any] | None = None):
        workflow_payload = payload.get("workflow") if payload and payload.get("workflow") else (payload if payload and payload.get("nodes") else None)
        workflow = Workflow.from_dict(workflow_payload) if workflow_payload else repository.get_workflow(workflow_id)
        if not workflow:
            record_studio_event("run_rejected", workflow_id=workflow_id, reason="workflow_not_found")
            raise HTTPException(404, "Workflow not found")
        if not payload or payload.get("confirmed") is not True or payload.get("confirmation_token") != confirmation_tokens.get(workflow_id):
            record_studio_event("run_rejected", workflow_id=workflow_id, reason="confirmation_required")
            raise HTTPException(409, "Explicit confirmation is required before API execution")
        validation = validate_workflow(workflow, require_public_assets=True)
        if not validation.valid:
            record_studio_event("run_rejected", workflow_id=workflow_id, reason="validation", errors=validation.errors)
            raise HTTPException(422, validation.as_dict())
        confirmation_tokens.pop(workflow_id, None)
        run_id = executor.run(workflow, node_ids=payload.get("node_ids"))
        return {"run_id": run_id, "status": "queued"}

    @app.post("/api/workflows/{workflow_id}/nodes/{node_id}/generate")
    def generate_node(workflow_id: str, node_id: str, payload: dict[str, Any] | None = None):
        """Confirm and execute exactly one generation node plus its ancestors."""
        workflow = Workflow.from_dict(payload.get("workflow")) if payload and payload.get("workflow") else repository.get_workflow(workflow_id)
        if not workflow or node_id not in workflow.node_map():
            raise HTTPException(404, "Workflow or node not found")
        if not payload or payload.get("confirmed") is not True:
            raise HTTPException(409, "Click the node's confirm generation button to start the API request")
        node = workflow.node_map()[node_id]
        if node.type not in {"image_generate", "video_generate"}:
            raise HTTPException(422, "Only image_generate and video_generate nodes can be run individually")
        validation = validate_workflow(workflow, require_public_assets=True)
        if not validation.valid:
            record_studio_event("run_rejected", workflow_id=workflow_id, node_id=node_id, errors=validation.errors)
            raise HTTPException(422, validation.as_dict())
        record_studio_event("run_requested", workflow_id=workflow_id, node_id=node_id, model=node.data.get("model"))
        run_id = executor.run(workflow, node_ids=[node_id])
        return {"run_id": run_id, "status": "queued", "node_id": node_id}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        run = repository.get_run(run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        return run

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str):
        async def stream():
            seen = 0
            for _ in range(600):
                items = executor.events.get(run_id, [])
                for event in items[seen:]:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                seen = len(items)
                if items and items[-1]["status"] in {"succeeded", "failed", "cancelled"}:
                    break
                await asyncio.sleep(0.5)
        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/assets/upload")
    async def upload_asset(file: UploadFile = File(...)):
        provider = configured_provider()
        filename = Path(file.filename or "upload.bin").name
        temp = PROJECT_ROOT / "output" / ".studio" / filename
        temp.parent.mkdir(parents=True, exist_ok=True)
        raw = await file.read()
        temp.write_bytes(raw)
        try:
            try:
                url = provider.upload(temp)
            except ValueError as exc:
                # With no S3/OSS provider configured, image-to-image can still
                # work: Seedream accepts a data URL as its reference image.
                # Videos intentionally do not use this fallback because
                # Seedance requires a publicly reachable URL.
                if (file.content_type or "").lower().startswith("image/"):
                    try:
                        url = image_bytes_to_data_url(raw, filename=filename, content_type=file.content_type)
                    except ValueError:
                        raise HTTPException(415, str(exc)) from exc
                else:
                    raise HTTPException(503, str(exc)) from exc
            except (RuntimeError, FileNotFoundError) as exc:
                raise HTTPException(503, str(exc)) from exc
        finally:
            temp.unlink(missing_ok=True)
        return {"url": url, "filename": filename}

    return app
