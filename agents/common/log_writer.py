"""Unified, date-partitioned JSONL logging for the project.

The writer intentionally keeps the file selection in one place.  Every write
checks the current date, creates that day's file when necessary, and appends a
single JSON object.  This makes request/result audit logs and error logs
consistent across the CLI clients and Studio backend.
"""

from __future__ import annotations

import json
import logging
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from agents.common import PROJECT_ROOT

LogCategory = Literal["request", "result", "error"]
LOG_ROOT = PROJECT_ROOT / "logs"

_locks: dict[Path, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(path, threading.Lock())


def daily_log_path(
    category: LogCategory | str,
    *,
    source: str | None = None,
    when: datetime | None = None,
    root: str | Path = LOG_ROOT,
) -> Path:
    """Return the JSONL path for *category* on the date of *when*.

    Files are named ``<source>_YYYY-MM-DD.jsonl`` (or
    ``<category>_YYYY-MM-DD.jsonl`` when no source is supplied), making the
    date visible in directory listings while preserving one append-only file
    per day and source.
    """
    moment = when or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    date = moment.astimezone(timezone.utc).strftime("%Y-%m-%d")
    safe_source = (source or str(category)).replace("/", "_").replace("\\", "_")
    return Path(root) / str(category) / f"{safe_source}_{date}.jsonl"


class DailyLogWriter:
    """Append JSON records to a date-partitioned category log.

    ``target`` may be a directory (the normal/default mode) or a concrete
    ``.jsonl`` file for callers that need backwards-compatible custom paths.
    Pass ``None`` to disable writing at the call site rather than constructing
    a writer.
    """

    def __init__(
        self,
        category: LogCategory | str,
        *,
        source: str | None = None,
        root: str | Path = LOG_ROOT,
        target: str | Path | None = None,
    ) -> None:
        if category not in {"request", "result", "error"}:
            raise ValueError(f"Unsupported log category: {category!r}")
        self.category = str(category)
        self.source = source or self.category
        self.root = Path(root)
        self.target = Path(target) if target is not None else None

    def path_for(self, when: datetime | None = None) -> Path:
        if self.target is not None and self.target.suffix.lower() in {".jsonl", ".log"}:
            return self.target
        if self.target is not None:
            moment = when or datetime.now(timezone.utc)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            date = moment.astimezone(timezone.utc).strftime("%Y-%m-%d")
            safe_source = self.source.replace("/", "_").replace("\\", "_")
            return self.target / f"{safe_source}_{date}.jsonl"
        return daily_log_path(self.category, source=self.source, when=when, root=self.root)

    def write(self, payload: dict[str, Any], *, when: datetime | None = None) -> Path:
        moment = when or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        record = {"timestamp_utc": moment.astimezone(timezone.utc).isoformat(timespec="seconds"), **payload}
        path = self.path_for(moment)
        path.parent.mkdir(parents=True, exist_ok=True)
        # A per-path lock prevents interleaved records from concurrent workers
        # in this process. Opening with ``a`` also provides the required
        # create-if-missing/append-if-present behavior.
        with _lock_for(path):
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return path

    def error(
        self,
        message: str,
        *,
        exc: BaseException | None = None,
        context: dict[str, Any] | None = None,
    ) -> Path:
        payload: dict[str, Any] = {
            "level": "ERROR",
            "message": message,
            "error_type": type(exc).__name__ if exc is not None else None,
        }
        if context:
            payload["context"] = context
        if exc is not None:
            payload["traceback"] = "".join(traceback.format_exception(exc))
        return self.write(payload)


_default_writers = {
    category: DailyLogWriter(category)
    for category in ("request", "result", "error")
}


def write_log(category: LogCategory | str, payload: dict[str, Any], **kwargs: Any) -> Path:
    """Write a request/result/error record through the shared interface."""
    return _default_writers[str(category)].write(payload, **kwargs)


def record_error(
    message: str,
    *,
    exc: BaseException | None = None,
    context: dict[str, Any] | None = None,
) -> Path:
    """Record an error in the date-partitioned ``logs/error`` directory."""
    return _default_writers["error"].error(message, exc=exc, context=context)


def write_request(payload: dict[str, Any], **kwargs: Any) -> Path:
    return write_log("request", payload, **kwargs)


def write_result(payload: dict[str, Any], **kwargs: Any) -> Path:
    return write_log("result", payload, **kwargs)


def write_error(message: str, *, exc: BaseException | None = None, context: dict[str, Any] | None = None) -> Path:
    return record_error(message, exc=exc, context=context)


# Friendly aliases for callers that prefer a generic logger name.
LogWriter = DailyLogWriter
UnifiedLogger = DailyLogWriter
get_daily_log_path = daily_log_path


class DailyErrorHandler(logging.Handler):
    """Route Python logging errors to the shared error writer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            exc = record.exc_info[1] if record.exc_info else None
            record_error(
                message,
                exc=exc,
                context={"logger": record.name, "level": record.levelname},
            )
        except Exception:
            # Logging must never crash the operation that emitted the error.
            pass


def install_error_logging() -> DailyErrorHandler:
    """Install one process-wide handler for ERROR+ records and return it."""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, DailyErrorHandler):
            return handler
    handler = DailyErrorHandler()
    handler.setLevel(logging.ERROR)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger.addHandler(handler)
    return handler


__all__ = [
    "LOG_ROOT",
    "DailyErrorHandler",
    "DailyLogWriter",
    "daily_log_path",
    "install_error_logging",
    "record_error",
    "write_log",
    "write_request",
    "write_result",
    "write_error",
    "LogWriter",
    "UnifiedLogger",
    "get_daily_log_path",
]
