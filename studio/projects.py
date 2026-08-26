from __future__ import annotations

from pathlib import Path

from agents.common import PROJECT_ROOT

DEFAULT_PROJECT_NAME = "default"
PROJECTS_ROOT = PROJECT_ROOT / "output" / "projects"


def validate_project_name(value: str | None) -> str:
    """Validate and normalize a single project directory name."""
    if not isinstance(value, str):
        raise ValueError("Project name is required")
    name = value.strip()
    if not name or name in {".", ".."}:
        raise ValueError("Project name must be a non-empty directory name")
    if any(char in name for char in ("/", "\\", ":", "*", "?", '"', "<", ">", "|")):
        raise ValueError("Project name must be a single safe directory name")
    if any(ord(char) < 32 for char in name):
        raise ValueError("Project name contains an invalid control character")
    return name


def ensure_projects_root() -> Path:
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
    (PROJECTS_ROOT / DEFAULT_PROJECT_NAME).mkdir(parents=True, exist_ok=True)
    return PROJECTS_ROOT


def project_directory(name: str | None, *, create: bool = True) -> Path:
    """Resolve a project name beneath ``output/projects`` safely."""
    normalized = validate_project_name(name or DEFAULT_PROJECT_NAME)
    root = ensure_projects_root().resolve()
    candidate = (root / normalized).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Project path must stay below output/projects") from exc
    if create:
        candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def list_project_names() -> list[str]:
    root = ensure_projects_root()
    return sorted(path.name for path in root.iterdir() if path.is_dir())