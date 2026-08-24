from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.common import PROJECT_ROOT

from .models import Workflow


class StudioRepository:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or PROJECT_ROOT / "output" / ".studio" / "studio.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        db = self._connect()
        try:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            db.commit()
        finally:
            db.close()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def save_workflow(self, workflow: Workflow) -> Workflow:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        db = self._connect()
        try:
            db.execute(
                "INSERT INTO workflows(id,title,payload,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET title=excluded.title,payload=excluded.payload,updated_at=excluded.updated_at",
                (workflow.id, workflow.title, json.dumps(workflow.to_dict(), ensure_ascii=False), now),
            )
            db.commit()
        finally:
            db.close()
        return workflow

    def get_workflow(self, workflow_id: str) -> Workflow | None:
        db = self._connect()
        try:
            row = db.execute("SELECT payload FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        finally:
            db.close()
        return Workflow.from_dict(json.loads(row["payload"])) if row else None

    def save_run(self, run_id: str, workflow_id: str, status: str, payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        db = self._connect()
        try:
            db.execute(
                "INSERT INTO runs(id,workflow_id,status,payload,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status,payload=excluded.payload,updated_at=excluded.updated_at",
                (run_id, workflow_id, status, json.dumps(payload, ensure_ascii=False, default=str), now),
            )
            db.commit()
        finally:
            db.close()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        db = self._connect()
        try:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        finally:
            db.close()
        if not row:
            return None
        return {"id": row["id"], "workflow_id": row["workflow_id"], "status": row["status"], **json.loads(row["payload"])}
