from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_script_project(project_dir: str | Path) -> dict[str, Any]:
    project_dir = Path(project_dir)
    result: dict[str, Any] = {}
    for filename in ("instances_prompt.yaml", "script.yaml"):
        path = project_dir / filename
        if path.exists():
            result[filename] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    markdown = project_dir / "script.md"
    if markdown.exists():
        result["script.md"] = markdown.read_text(encoding="utf-8")
    if not result:
        raise FileNotFoundError(f"No script contract files found in {project_dir}")
    return result


def write_script_project(project_dir: str | Path, payload: dict[str, Any]) -> Path:
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    for filename in ("instances_prompt.yaml", "script.yaml"):
        if filename in payload:
            (project_dir / filename).write_text(yaml.safe_dump(payload[filename], allow_unicode=True, sort_keys=False), encoding="utf-8")
    if "script.md" in payload:
        (project_dir / "script.md").write_text(str(payload["script.md"]), encoding="utf-8")
    return project_dir
