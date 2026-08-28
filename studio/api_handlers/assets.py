from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException, UploadFile

from agents.common import PROJECT_ROOT
from agents.common.log_writer import record_error

from ..storage import image_bytes_to_data_url


async def upload_asset(file: UploadFile, provider_factory: Callable[[], Any]) -> dict[str, str]:
    """Upload an asset, with an inline image fallback when no provider exists."""
    provider = provider_factory()
    filename = Path(file.filename or "upload.bin").name
    temp = PROJECT_ROOT / "output" / ".studio" / filename
    temp.parent.mkdir(parents=True, exist_ok=True)
    raw = await file.read()
    temp.write_bytes(raw)
    try:
        try:
            url = provider.upload(temp)
        except ValueError as exc:
            if (file.content_type or "").lower().startswith("image/"):
                try:
                    url = image_bytes_to_data_url(raw, filename=filename, content_type=file.content_type)
                except ValueError:
                    raise HTTPException(415, str(exc)) from exc
            else:
                raise HTTPException(503, str(exc)) from exc
        except (RuntimeError, FileNotFoundError) as exc:
            record_error("Studio asset upload failed", exc=exc, context={"filename": filename})
            raise HTTPException(503, str(exc)) from exc
    finally:
        temp.unlink(missing_ok=True)
    return {"url": url, "filename": filename}

