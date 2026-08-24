from __future__ import annotations

import base64
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse


_INLINE_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


def image_bytes_to_data_url(raw: bytes, *, filename: str = "image", content_type: str | None = None) -> str:
    """Encode image bytes as a Seedream-compatible data URL.

    Seedream accepts a public URL or an inline ``data:image/...;base64`` value
    for image-to-image requests.  Keeping this conversion in the storage layer
    lets both the HTTP upload endpoint and workflow executor handle local image
    files consistently when no object-storage provider is configured.
    """
    mime_type = (content_type or mimetypes.guess_type(filename)[0] or "").lower()
    if mime_type not in _INLINE_IMAGE_MIME_TYPES:
        raise ValueError("image must be a JPEG, PNG, or WebP file")
    return f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}"


def image_file_to_data_url(path: str | Path) -> str:
    """Read a local JPEG/PNG/WebP file and return an inline data URL."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    return image_bytes_to_data_url(path.read_bytes(), filename=path.name)


class StorageProvider(Protocol):
    def resolve(self, value: str) -> str: ...
    def upload(self, path: str | Path) -> str: ...


class UrlProvider:
    """Pass through public URLs and reject local files for API execution."""

    def resolve(self, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("asset is not a public http(s) URL; configure an uploader")
        return value

    def upload(self, path: str | Path) -> str:
        raise ValueError("no upload provider configured for local assets")


class S3CompatibleProvider:
    """Small adapter for OSS/S3-compatible services.

    The optional boto3 dependency is imported only when this provider is used.
    """

    def __init__(self, *, endpoint: str, bucket: str, public_base_url: str, region: str | None = None):
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket
        self.public_base_url = public_base_url.rstrip("/")
        self.region = region

    @classmethod
    def from_env(cls) -> "S3CompatibleProvider | None":
        endpoint = os.getenv("VIDEO_AGENT_S3_ENDPOINT")
        bucket = os.getenv("VIDEO_AGENT_S3_BUCKET")
        public_base_url = os.getenv("VIDEO_AGENT_S3_PUBLIC_BASE_URL")
        if not endpoint or not bucket or not public_base_url:
            return None
        return cls(endpoint=endpoint, bucket=bucket, public_base_url=public_base_url, region=os.getenv("VIDEO_AGENT_S3_REGION"))

    def resolve(self, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return value
        return self.upload(value)

    def upload(self, path: str | Path) -> str:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 is required for S3-compatible uploads") from exc
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        key = f"video-agent/{path.name}"
        client = boto3.client("s3", endpoint_url=self.endpoint, region_name=self.region)
        client.upload_file(str(path), self.bucket, key)
        return f"{self.public_base_url}/{key}"


def configured_provider() -> StorageProvider:
    return S3CompatibleProvider.from_env() or UrlProvider()
