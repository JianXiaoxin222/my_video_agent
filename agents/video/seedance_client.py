"""Non-interactive Seedance 2.0 video generation client.

Replaces the interactive demo_standard.py pattern with a clean, reusable class
suitable for automation and CLI scripting.

Usage::

    from seedance_client import SeedanceClient

    client = SeedanceClient()                     # reads ARK_API_KEY from env/config
    task_id = client.create_task(
        content=[
            {"type": "text", "text": "A cat walking on a sunny beach"},
        ],
        duration=5,
        ratio="16:9",
    )
    result = client.poll_task(task_id)
    path = client.download_video(result.content.video_url, "download/output.mp4")
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from volcenginesdkarkruntime import Ark

from agents.common import PROJECT_ROOT
from agents.common.ark_auth import resolve_ark_api_key
from agents.common.config_loader import load_config_or_default

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config & request-log constants
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = "config/seedance.yaml"

# Where each video-generation request payload is recorded (JSONL, one JSON
# object per line). This is the inspectable intermediate artifact showing
# exactly what prompt/content was sent to the Seedance API.
_DEFAULT_REQUEST_LOG = (
    PROJECT_ROOT / "logs" / "seedance_requests.jsonl"
)

# Where each completed video-generation RESULT is recorded (JSONL, one JSON
# object per line) — the task_id and returned public video_url, for later
# lookup/reuse (e.g. chaining a scene's video into the next as reference_video).
_DEFAULT_RESULT_LOG = (
    PROJECT_ROOT / "logs" / "seedance_results.jsonl"
)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class SeedanceClient:
    """Non-interactive wrapper around the Ark Seedance 2.0 video generation API.

    Args:
        api_key: Ark API key. If None, resolved from env / config files.
        config_path: Path to seedance.yaml (relative to project root or absolute).
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
        # Resolve config
        self._cfg = load_config_or_default(config_path, default={})
        sd_cfg = self._cfg.get("seedance", {}) if self._cfg else {}

        # Resolve API key
        self._api_key = resolve_ark_api_key(explicit_key=api_key)

        # Resolve base URL
        if base_url is None:
            base_url = sd_cfg.get("base_url", "https://ark.cn-beijing.volces.com/api/v3")

        # Initialize SDK client
        self._client = Ark(api_key=self._api_key, base_url=base_url)

        # Store defaults
        self._defaults = sd_cfg.get("defaults", {})
        self._models = sd_cfg.get("models", {})
        self._retry_cfg = sd_cfg.get("retry", {})

        # Where to record each video-generation request payload (None = disabled)
        self._request_log_path = (
            Path(request_log_path) if request_log_path is not None else None
        )
        # Where to record each completed video-generation result (None = disabled)
        self._result_log_path = (
            Path(result_log_path) if result_log_path is not None else None
        )

    def _record_request(self, payload: dict[str, Any]) -> None:
        """Append a video-generation request payload to the request log (JSONL).

        One JSON object per line, capturing exactly what will be sent to the
        Seedance API: model, ratio, duration, watermark, generate_audio, and the
        full ``content`` array (the actual prompt text). This is the inspectable
        intermediate artifact used to audit what the agent conveyed to the API.
        """
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
            logger.exception(
                "Failed to record request payload to %s", self._request_log_path
            )

    def _record_result(
        self,
        task_id: str,
        model: str | None,
        video_url: str | None,
    ) -> None:
        """Append a completed video-generation result to the result log (JSONL).

        Records the public video URL returned by the API alongside the task_id,
        so callers can later reuse the URL directly as a Seedance
        ``reference_video`` (e.g. chaining one scene's video into the next)
        without re-uploading.
        """
        if self._result_log_path is None:
            return
        try:
            self._result_log_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "task_id": task_id,
                "model": model,
                "video_url": video_url,
            }
            with open(self._result_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            logger.exception("Failed to record video result to %s", self._result_log_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def default_model(self) -> str:
        """The default model ID from config."""
        return self._models.get("default", "doubao-seedance-2-0-mini-260615")

    @property
    def pro_model(self) -> str:
        """The pro model ID from config."""
        return self._models.get("pro", "doubao-seedance-2-0-260128")

    def create_task(
        self,
        content: list[dict[str, Any]],
        model: str | None = None,
        ratio: str | None = None,
        duration: int | None = None,
        watermark: bool | None = None,
        generate_audio: bool | None = None,
        resolution: str | None = None,
        return_last_frame: bool | None = None,
        **kwargs: Any,
    ) -> str:
        """Create a video generation task.

        Args:
            content: List of content blocks. Each dict must have a "type" key:
                - {"type": "text", "text": "..."}
                - {"type": "image_url", "image_url": {"url": "..."}, "role": "reference_image"}
                - {"type": "video_url", "video_url": {"url": "..."}, "role": "reference_video"}
                - {"type": "audio_url", "audio_url": {"url": "..."}, "role": "reference_audio"}
            model: Model ID. Uses default from config if None.
            ratio: Aspect ratio ("16:9", "9:16", "1:1"). Uses config default if None.
            duration: Video duration in seconds. Uses config default if None.
            watermark: Whether to add watermark. Uses config default if None.
            generate_audio: Whether to generate audio. Uses config default if None.
            resolution: Output resolution (480p/720p/1080p/4k), if supported by model.
            return_last_frame: Whether to return the generated video's last-frame image.
            **kwargs: Additional API parameters (callback_url, seed, resolution, etc.).

        Returns:
            Task ID string.

        Raises:
            Exception: On API error.
        """
        if model is None:
            model = self.default_model
        if ratio is None:
            ratio = self._defaults.get("ratio", "16:9")
        if duration is None:
            duration = self._defaults.get("duration", 5)
        if watermark is None:
            watermark = self._defaults.get("watermark", False)
        if generate_audio is None:
            generate_audio = self._defaults.get("generate_audio", True)
        if resolution is None:
            resolution = self._defaults.get("resolution")
        if return_last_frame is None:
            return_last_frame = self._defaults.get("return_last_frame")

        logger.info(
            "Creating Seedance task: model=%s, ratio=%s, duration=%ds, "
            "content_types=%s",
            model,
            ratio,
            duration,
            [b.get("type") for b in content],
        )

        # Record the exact request payload as an inspectable intermediate artifact.
        payload: dict[str, Any] = {
            "model": model,
            "ratio": ratio,
            "duration": duration,
            "watermark": watermark,
            "generate_audio": generate_audio,
            "content": content,
        }
        if resolution is not None:
            payload["resolution"] = resolution
        if return_last_frame is not None:
            payload["return_last_frame"] = return_last_frame
        if kwargs:
            payload["extra_params"] = kwargs
        self._record_request(payload)

        result = self._client.content_generation.tasks.create(
            model=model,
            content=content,
            ratio=ratio,
            duration=duration,
            watermark=watermark,
            generate_audio=generate_audio,
            **({"resolution": resolution} if resolution is not None else {}),
            **({"return_last_frame": return_last_frame} if return_last_frame is not None else {}),
            **kwargs,
        )

        task_id: str = result.id
        logger.info("Task created: %s", task_id)
        return task_id

    def get_task(self, task_id: str) -> Any:
        """Get the current status and result of a task.

        Args:
            task_id: The task ID returned by :meth:`create_task`.

        Returns:
            ContentGenerationTask object with .id, .status, .content.video_url, etc.
        """
        return self._client.content_generation.tasks.get(task_id=task_id)

    def poll_task(
        self,
        task_id: str,
        poll_interval: int | None = None,
        timeout: int | None = None,
        on_status: callable | None = None,
    ) -> Any:
        """Poll a task until it succeeds or fails.

        Args:
            task_id: The task ID to poll.
            poll_interval: Seconds between status checks. Uses config default if None.
            timeout: Maximum total wait time in seconds. Uses config default if None.
            on_status: Optional callback(status_string) called on each poll.

        Returns:
            Completed ContentGenerationTask with .status == "succeeded".

        Raises:
            TimeoutError: If the task doesn't complete within *timeout* seconds.
            RuntimeError: If the task fails (.status == "failed").
        """
        if poll_interval is None:
            poll_interval = self._defaults.get("poll_interval", 30)
        if timeout is None:
            timeout = self._defaults.get("poll_timeout", 600)

        start_time = time.time()
        attempt = 0

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise TimeoutError(
                    f"Task {task_id} did not complete within {timeout}s "
                    f"(current status unknown, call get_task() to check)"
                )

            result = self.get_task(task_id)
            status = result.status
            attempt += 1

            if on_status:
                on_status(status)

            if status == "succeeded":
                logger.info("Task %s succeeded after %d attempts (%.0fs).", task_id, attempt, elapsed)
                video_url = getattr(getattr(result, "content", None), "video_url", None)
                self._record_result(
                    task_id=task_id,
                    model=getattr(result, "model", None),
                    video_url=video_url,
                )
                return result
            elif status == "failed":
                error_msg = getattr(result, "error", None)
                raise RuntimeError(
                    f"Task {task_id} failed after {attempt} attempts: {error_msg}"
                )
            else:
                logger.debug(
                    "Task %s status: %s (attempt %d, elapsed %.0fs) — "
                    "sleeping %ds",
                    task_id, status, attempt, elapsed, poll_interval,
                )
                time.sleep(poll_interval)

    def download_video(
        self,
        video_url: str,
        output_path: str | Path,
        chunk_size: int = 1024 * 1024,  # 1 MiB
    ) -> Path:
        """Download a generated video to a local file.

        Args:
            video_url: The video URL from the completed task (result.content.video_url).
            output_path: Destination file path. Parent directories are created if needed.
            chunk_size: Download chunk size in bytes.

        Returns:
            Path to the downloaded file.

        Raises:
            httpx.HTTPError: On download failure.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Downloading video from %s → %s", video_url, output_path)

        with httpx.Client(timeout=300, follow_redirects=True) as http:
            with http.stream("GET", video_url) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0)) or None

                downloaded = 0
                with open(output_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=chunk_size):
                        f.write(chunk)
                        downloaded += len(chunk)

        file_size_mb = downloaded / (1024 * 1024)
        logger.info("Downloaded %.1f MiB → %s", file_size_mb, output_path)
        return output_path

    # ------------------------------------------------------------------
    # Convenience: create + poll + download in one call
    # ------------------------------------------------------------------

    def generate(
        self,
        content: list[dict[str, Any]],
        output_path: str | Path,
        model: str | None = None,
        ratio: str | None = None,
        duration: int | None = None,
        watermark: bool | None = None,
        generate_audio: bool | None = None,
        resolution: str | None = None,
        return_last_frame: bool | None = None,
        poll_interval: int | None = None,
        timeout: int | None = None,
        **kwargs: Any,
    ) -> Path:
        """Create a task, poll until complete, and download the video.

        This is the all-in-one convenience method. For finer control, use
        :meth:`create_task` + :meth:`poll_task` + :meth:`download_video` separately.

        Args:
            content: Content blocks (see :meth:`create_task`).
            output_path: Where to save the downloaded video.
            model: Model ID.
            ratio: Aspect ratio.
            duration: Video duration in seconds.
            watermark: Whether to add watermark.
            generate_audio: Whether to generate audio.
            resolution: Output resolution.
            return_last_frame: Whether to return the generated video's last-frame image.
            poll_interval: Seconds between status checks.
            timeout: Max wait time in seconds.
            **kwargs: Additional parameters passed to :meth:`create_task`.

        Returns:
            Path to the downloaded video file.
        """
        task_id = self.create_task(
            content=content,
            model=model,
            ratio=ratio,
            duration=duration,
            watermark=watermark,
            generate_audio=generate_audio,
            resolution=resolution,
            return_last_frame=return_last_frame,
            **kwargs,
        )

        result = self.poll_task(
            task_id,
            poll_interval=poll_interval,
            timeout=timeout,
        )

        return self.download_video(result.content.video_url, output_path)
