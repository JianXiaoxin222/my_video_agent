from __future__ import annotations

from typing import Any

from agents.common.config_loader import load_config_or_default

from ..audit import record_studio_event


def health() -> dict[str, Any]:
    """Return the backend health status."""
    return {"ok": True, "service": "video-agent-studio"}


def client_error(payload: dict[str, Any]) -> dict[str, bool]:
    """Record a UI-visible error in the Studio audit log."""
    record_studio_event(
        "client_error",
        source="studio-ui",
        action=str(payload.get("action") or "unknown"),
        message=str(payload.get("message") or "Unknown UI error"),
        status_code=payload.get("status_code"),
        edge_id=payload.get("edge_id"),
        source_node=payload.get("source_node"),
        source_port=payload.get("source_port"),
        target_node=payload.get("target_node"),
        target_port=payload.get("target_port"),
        reason=payload.get("reason"),
    )
    return {"ok": True}


def models() -> dict[str, Any]:
    """Return configured image and video model options."""
    image_cfg = load_config_or_default("config/seedream.yaml", default={}).get("seedream", {})
    video_cfg = load_config_or_default("config/seedance.yaml", default={}).get("seedance", {})
    image_models = image_cfg.get("models", {})
    video_models = video_cfg.get("models", {})
    image_default = image_models.get("default", "doubao-seedream-5-0-pro-260628")
    video_default = video_models.get("default", "doubao-seedance-2-0-mini-260615")
    return {
        "image": {"default": image_default, "options": [image_default]},
        "video": {
            "default": video_default,
            "options": [video_default, video_models.get("pro", "doubao-seedance-2-0-260128")],
        },
    }

