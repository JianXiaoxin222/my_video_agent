from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..projects import list_project_names, project_directory, validate_project_name


def list_projects() -> dict[str, Any]:
    """List available Studio projects."""
    return {"projects": list_project_names(), "default": "default"}


def create_project(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a project directory if it does not already exist."""
    try:
        name = validate_project_name(payload.get("name"))
        existing = project_directory(name, create=False).exists()
        project_directory(name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(409, f"Project directory cannot be created: {exc}") from exc
    return {"name": name, "created": not existing}

