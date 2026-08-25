from __future__ import annotations

from typing import Any

from agents.common.log_writer import DailyLogWriter, record_error


def record_studio_event(event: str, **payload: Any) -> None:
    """Record a Studio event in the appropriate date-partitioned log.

    Rejected runs and client/API errors belong in ``logs/error``; successful
    lifecycle events belong in ``logs/result``.
    """
    record = {"event": event, **payload}
    if event == "client_error" or event.endswith("_error") or event.endswith("_rejected") or event in {"failed", "error"}:
        record_error(str(payload.get("message") or event), context=record)
        return
    category = "request" if event.endswith("_requested") or event == "request" else "result"
    DailyLogWriter(category, source="studio").write(record)
