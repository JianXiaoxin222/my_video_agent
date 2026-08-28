from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from .context import ApiContext


def get_run(ctx: ApiContext, run_id: str):
    run = ctx.repository.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


def events(ctx: ApiContext, run_id: str) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        seen = 0
        for _ in range(600):
            items = ctx.executor.events.get(run_id, [])
            for event in items[seen:]:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            seen = len(items)
            if items and items[-1]["status"] in {"succeeded", "failed", "cancelled"}:
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream")

