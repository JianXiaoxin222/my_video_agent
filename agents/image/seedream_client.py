"""Non-interactive Seedream 5.0 Pro (火山方舟 Ark) image generation client.

A clean, reusable class for automation and CLI scripting, mirroring
``agents/video/seedance_client.py``. It uses the SAME Ark platform and API key
as the video client — only the model and the endpoint differ.

Image generation is synchronous (``POST /images/generations``): the response
carries either a downloadable JPEG/PNG URL (``response_format="url"``) or a
Base64 payload (``response_format="b64_json"``).

Usage::

    from agents.image.seedream_client import SeedreamClient

    client = SeedreamClient()                     # reads ARK_API_KEY from env/config
    path = client.generate(
        prompt="4-year-old Border Collie, photorealistic ...",
        output_path="character_images/旺财.jpg",
        size="2K",
    )
"""

from __future__ import annotations

import base64
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from volcenginesdkarkruntime import Ark

from agents.common import PROJECT_ROOT
from agents.common.ark_auth import resolve_seedream_api_key
from agents.common.config_loader import load_config_or_default

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = "config/seedream.yaml"

# Where each image-generation request payload is recorded (JSONL, one JSON
# object per line) — the inspectable audit log of what prompt was sent.
_DEFAULT_REQUEST_LOG = PROJECT_ROOT / "logs" / "seedream_requests.jsonl"

# Where each image-generation RESULT is recorded (JSONL, one JSON object per
# line) — the returned public image URL + local path, for later lookup/reuse
# (e.g. as a Seedance ``reference_image`` without re-uploading).
_DEFAULT_RESULT_LOG = PROJECT_ROOT / "logs" / "seedream_results.jsonl"


class SeedreamClient:
    """Wrapper around the Ark Seedream 5.0 Pro image generation API.

    Args:
        api_key: Ark API key. If None, resolved from env / config files.
        config_path: Path to seedream.yaml (relative to project root or absolute).
        base_url: Ark platform base URL. If None, read from config.
        request_log_path: JSONL path for request auditing (None = disabled).
        result_log_path: JSONL path for result recording (None = disabled).
    """

    def __init__(
        self,
        api_key: str | None = None,
        config_path: str = _DEFAULT_CONFIG_PATH,
        base_url: str | None = None,
        request_log_path: str | Path | None = _DEFAULT_REQUEST_LOG,
        result_log_path: str | Path | None = _DEFAULT_RESULT_LOG,
    ):
        # Resolve config (defaults to {} when the file is absent).
        self._cfg = load_config_or_default(config_path, default={})
        sr_cfg = self._cfg.get("seedream", {}) if self._cfg else {}

        # Resolve the image-specific Ark key (separate from the video key).
        self._api_key = resolve_seedream_api_key(explicit_key=api_key)

        if base_url is None:
            base_url = sr_cfg.get("base_url", "https://ark.cn-beijing.volces.com/api/v3")

        self._client = Ark(api_key=self._api_key, base_url=base_url)

        self._defaults = sr_cfg.get("defaults", {})
        self._models = sr_cfg.get("models", {})
        self._retry_cfg = sr_cfg.get("retry", {})

        self._request_log_path = (
            Path(request_log_path) if request_log_path is not None else None
        )
        self._result_log_path = (
            Path(result_log_path) if result_log_path is not None else None
        )

    @property
    def default_model(self) -> str:
        """The default image model ID from config."""
        return self._models.get("default", "doubao-seedream-5-0-pro-260628")

    def _record_request(self, payload: dict[str, Any]) -> None:
        """Append an image-generation request payload to the audit log (JSONL)."""
        if self._request_log_path is None:
            return
        try:
            self._request_log_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                **payload,
            }
            with open(self._request_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            logger.exception("Failed to record request payload to %s", self._request_log_path)

    def _record_result(
        self,
        model: str,
        prompt: str,
        image_url: str | None,
        output_path: str | Path | None,
    ) -> None:
        """Append a completed image-generation result to the result log (JSONL).

        Records the public image URL returned by the API alongside the local
        path, so callers can later reuse the URL directly as a Seedance
        ``reference_image`` without re-uploading. ``image_url`` is None when the
        response was Base64 (which has no public URL).
        """
        if self._result_log_path is None:
            return
        try:
            self._result_log_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "model": model,
                "prompt": prompt,
                "image_url": image_url,
                "output_path": str(output_path) if output_path is not None else None,
            }
            with open(self._result_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            logger.exception("Failed to record image result to %s", self._result_log_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_image(
        self,
        prompt: str,
        reference_image: str | list[str] | None = None,
        model: str | None = None,
        size: str | None = None,
        watermark: bool | None = None,
        response_format: str | None = None,
        seed: int | None = None,
        output_format: str | None = None,
    ) -> str:
        """Generate a single image and return its URL (or Base64 string).

        Args:
            prompt: English text prompt describing the image.
            reference_image: Optional public URL/data URL, or an ordered list of
                them for multi-image image-to-image generation.
            model: Model ID. Uses config default if None.
            size: "1K"/"1.5K"/"2K" or "WxH". Uses config default if None.
            watermark: Whether to add the "AI generated" watermark.
            response_format: "url" or "b64_json". Uses config default if None.
            seed: Optional reproducible seed.
            output_format: Optional "png"/"jpeg" (None = model default).

        Returns:
            Image URL when ``response_format="url"``, else a Base64 string.

        Raises:
            RuntimeError: If the API returns an error or no image.
        """
        if model is None:
            model = self.default_model
        if size is None:
            size = self._defaults.get("size", "2K")
        if watermark is None:
            watermark = self._defaults.get("watermark", False)
        if response_format is None:
            response_format = self._defaults.get("response_format", "url")
        if seed is None:
            seed = self._defaults.get("seed")
        if output_format is None:
            output_format = self._defaults.get("output_format")

        logger.info(
            "Generating image: model=%s, size=%s, response_format=%s, watermark=%s",
            model, size, response_format, watermark,
        )

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "watermark": watermark,
            "response_format": response_format,
        }
        if reference_image:
            # Avoid writing a potentially large Base64 image into the JSONL log.
            references = reference_image if isinstance(reference_image, list) else [reference_image]
            payload["image"] = [
                "<data-url omitted>" if item.startswith("data:") else item
                for item in references
            ]
            if not isinstance(reference_image, list):
                payload["image"] = payload["image"][0]
        if seed is not None:
            payload["seed"] = seed
        if output_format is not None:
            payload["output_format"] = output_format
        self._record_request(payload)

        request: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "watermark": watermark,
            "response_format": response_format,
            "seed": seed,
            "output_format": output_format,
        }
        if reference_image:
            request["image"] = reference_image

        result = self._client.images.generate(**request)

        # Surface API-side errors (e.g. model not opened / insufficient quota).
        error = getattr(result, "error", None)
        if error is not None:
            message = getattr(error, "message", None) or str(error)
            code = getattr(error, "code", None)
            raise RuntimeError(
                f"Image generation failed (code={code}): {message}"
            )

        data = getattr(result, "data", None)
        if not data:
            raise RuntimeError("Image generation returned no image data.")

        image = data[0]
        if response_format == "b64_json":
            b64 = getattr(image, "b64_json", None)
            if not b64:
                raise RuntimeError("Image generation returned empty b64_json.")
            return b64
        return getattr(image, "url", None) or ""

    def download_image(
        self,
        image_url: str,
        output_path: str | Path,
        chunk_size: int = 1024 * 1024,  # 1 MiB
    ) -> Path:
        """Download a generated image URL to a local file.

        Returns:
            Path to the downloaded file.

        Raises:
            httpx.HTTPError: On download failure.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Downloading image from %s → %s", image_url, output_path)

        with httpx.Client(timeout=300, follow_redirects=True) as http:
            with http.stream("GET", image_url) as response:
                response.raise_for_status()
                with open(output_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=chunk_size):
                        f.write(chunk)

        logger.info("Saved image → %s", output_path)
        return output_path

    def _save_b64(
        self,
        b64: str,
        output_path: str | Path,
    ) -> Path:
        """Decode a Base64 image payload and write it to disk."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        raw = base64.b64decode(b64)
        output_path.write_bytes(raw)
        logger.info("Saved image (b64) → %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Convenience: generate + persist in one call
    # ------------------------------------------------------------------

    def generate_image_url(
        self,
        prompt: str,
        output_path: str | Path,
        reference_image: str | list[str] | None = None,
        model: str | None = None,
        size: str | None = None,
        watermark: bool | None = None,
        response_format: str | None = None,
        seed: int | None = None,
        output_format: str | None = None,
    ) -> tuple[Path, str]:
        """Generate one image, save it locally, and return ``(path, public_url)``.

        Unlike :meth:`generate`, this also returns the public image URL returned
        by the API so callers can reuse it directly as a Seedance
        ``reference_image`` (no re-upload required). When
        ``response_format="b64_json"`` the URL is ``""`` (Base64 has no public
        URL). The result (URL + local path) is appended to the result log.

        Returns:
            ``(Path, str)`` — saved file path and public URL (or ``""`` for b64).
        """
        if response_format is None:
            response_format = self._defaults.get("response_format", "url")

        result = self.generate_image(
            prompt=prompt,
            reference_image=reference_image,
            model=model,
            size=size,
            watermark=watermark,
            response_format=response_format,
            seed=seed,
            output_format=output_format,
        )

        if response_format == "b64_json":
            path = self._save_b64(result, output_path)
            self._record_result(
                model=model or self.default_model,
                prompt=prompt,
                image_url=None,
                output_path=path,
            )
            return path, ""

        if not result:
            raise RuntimeError("Image generation returned an empty URL.")

        path = self.download_image(result, output_path)
        self._record_result(
            model=model or self.default_model,
            prompt=prompt,
            image_url=result,
            output_path=path,
        )
        return path, result

    def generate(
        self,
        prompt: str,
        output_path: str | Path,
        reference_image: str | list[str] | None = None,
        model: str | None = None,
        size: str | None = None,
        watermark: bool | None = None,
        response_format: str | None = None,
        seed: int | None = None,
        output_format: str | None = None,
    ) -> Path:
        """Generate one image and save it to ``output_path``.

        Returns:
            Path to the saved image file.
        """
        path, _url = self.generate_image_url(
            prompt=prompt,
            output_path=output_path,
            reference_image=reference_image,
            model=model,
            size=size,
            watermark=watermark,
            response_format=response_format,
            seed=seed,
            output_format=output_format,
        )
        return path
