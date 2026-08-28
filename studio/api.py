"""FastAPI application and route catalogue for Video Agent Studio.

Route declarations live here as the single API index. Business behavior is
implemented in studio.api_handlers modules grouped by domain.
"""

from typing import Any

from agents.common import PROJECT_ROOT
from agents.common.log_writer import install_error_logging

from .api_handlers import assets, logs, projects, runs, system, workflows
from .api_handlers.context import ApiContext
from .executor import WorkflowExecutor
from .repository import StudioRepository
from .storage import configured_provider

install_error_logging()


def create_app():
    """Build the Studio FastAPI app and register every public endpoint."""
    try:
        from fastapi import FastAPI, File, UploadFile
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        from agents.common.log_writer import record_error
        record_error("Studio dependencies are unavailable", exc=exc)
        raise RuntimeError("Install FastAPI and Uvicorn with: pip install -r requirements.txt") from exc

    app = FastAPI(title="Video Agent Studio", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/outputs", StaticFiles(directory=PROJECT_ROOT / "output"), name="outputs")
    repository = StudioRepository()
    context = ApiContext(repository=repository, executor=WorkflowExecutor(repository))

    # System
    @app.get("/api/health")
    def health():
        return system.health()

    @app.post("/api/client-errors")
    def client_error(payload: dict[str, Any]):
        return system.client_error(payload)

    @app.get("/api/models")
    def models():
        return system.models()

    # Projects and logs
    @app.get("/api/projects")
    def list_projects():
        return projects.list_projects()

    @app.post("/api/projects")
    def create_project(payload: dict[str, Any]):
        return projects.create_project(payload)

    @app.get("/api/logs/runs")
    def run_logs(limit: int = 100):
        return logs.run_logs(limit)

    # Workflows
    @app.post("/api/workflows")
    def create_workflow(payload: dict[str, Any]):
        return workflows.create_workflow(context, payload)

    @app.get("/api/workflows/{workflow_id}")
    def get_workflow(workflow_id: str):
        return workflows.get_workflow(context, workflow_id)

    @app.put("/api/workflows/{workflow_id}")
    def update_workflow(workflow_id: str, payload: dict[str, Any]):
        return workflows.update_workflow(context, workflow_id, payload)

    @app.post("/api/workflows/{workflow_id}/validate")
    def validate_workflow(workflow_id: str, payload: dict[str, Any] | None = None):
        return workflows.validate(context, workflow_id, payload)

    @app.post("/api/workflows/{workflow_id}/preview")
    def preview_workflow(workflow_id: str, payload: dict[str, Any] | None = None):
        return workflows.preview(context, workflow_id, payload)

    @app.post("/api/workflows/{workflow_id}/runs")
    def run_workflow(workflow_id: str, payload: dict[str, Any] | None = None):
        return workflows.run(context, workflow_id, payload)

    @app.post("/api/workflows/{workflow_id}/nodes/{node_id}/generate")
    def generate_node(workflow_id: str, node_id: str, payload: dict[str, Any] | None = None):
        return workflows.generate_node(context, workflow_id, node_id, payload)

    # Runs and SSE events
    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        return runs.get_run(context, run_id)

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str):
        return runs.events(context, run_id)

    # Assets
    @app.post("/api/assets/upload")
    async def upload_asset(file: UploadFile = File(...)):
        # Resolve at request time so tests can replace studio.api.configured_provider.
        return await assets.upload_asset(file, configured_provider)

    return app
