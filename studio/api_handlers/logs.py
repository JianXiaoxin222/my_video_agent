from __future__ import annotations

import json
from typing import Any

from agents.common import PROJECT_ROOT


def run_logs(limit: int = 100) -> dict[str, Any]:
    """Read and normalize Studio run and error log entries."""
    paths = sorted((PROJECT_ROOT / "logs" / "result").glob("studio_*.jsonl"))
    paths += sorted((PROJECT_ROOT / "logs" / "error").glob("error_*.jsonl"))
    legacy = PROJECT_ROOT / "logs" / "studio_runs.jsonl"
    if legacy.exists():
        paths.append(legacy)
    entries: list[dict[str, Any]] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
                context = entry.get("context")
                if isinstance(context, dict) and context.get("event"):
                    entry = {**context, "timestamp_utc": entry.get("timestamp_utc"), "log_level": entry.get("level"), "message": entry.get("message")}
                entries.append(entry)
            except json.JSONDecodeError:
                entries.append({"raw": line})
    entries.sort(key=lambda item: item.get("timestamp_utc", ""))
    return {"entries": entries[-max(1, min(limit, 500)):]} 

