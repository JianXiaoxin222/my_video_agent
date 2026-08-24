from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.common import PROJECT_ROOT


def record_studio_event(event: str, **payload: Any) -> None:
    """Append a redacted Studio lifecycle event to a durable JSONL log."""
    path = PROJECT_ROOT / "logs" / "studio_runs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        **payload,
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
