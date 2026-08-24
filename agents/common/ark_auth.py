"""Shared Ark (火山方舟) API key resolution.

Seedance (video) and Seedream (image) are both ByteDance models served on the
same Volcano Ark platform, but they use *separate* API keys so token/usage can
be tracked independently. This module centralises the resolution logic while
keeping the two providers' keys distinct.

Resolution priority (identical shape for both providers):

    1. Explicit constructor argument
    2. A dedicated environment variable
    3. ``config/secrets.yaml`` — a dedicated section

  - Video (Seedance): ``ARK_API_KEY`` env var → ``ark.api_key`` (fallback
    ``seedance.api_key``).
  - Image (Seedream): ``SEEDREAM_API_KEY`` env var → ``seedream.api_key``.
"""

from __future__ import annotations

import os

from agents.common import PROJECT_ROOT


def _load_key_from_secrets(sections: tuple[str, ...]) -> str | None:
    """Read an API key from the first populated ``config/secrets.yaml`` section.

    Placeholder values (``${ARK_API_KEY}`` / ``your-...``) are treated as absent.
    """
    try:
        secrets_path = PROJECT_ROOT / "config" / "secrets.yaml"
        if not secrets_path.exists():
            return None

        import yaml as _yaml

        with open(secrets_path, "r", encoding="utf-8") as f:
            data = _yaml.safe_load(f)

        if isinstance(data, dict):
            for section in sections:
                key = data.get(section, {}).get("api_key", "")
                if key and key != "${ARK_API_KEY}" and not key.startswith("your-"):
                    return key
    except Exception:
        pass
    return None


def load_ark_key_from_secrets() -> str | None:
    """Read the video (Seedance) Ark API key from ``config/secrets.yaml``."""
    return _load_key_from_secrets(("ark", "seedance"))


def load_seedream_key_from_secrets() -> str | None:
    """Read the image (Seedream) Ark API key from ``config/secrets.yaml``."""
    return _load_key_from_secrets(("seedream",))


def resolve_ark_api_key(explicit_key: str | None = None) -> str:
    """Resolve the video (Seedance) Ark API key.

    Priority: explicit arg → ``ARK_API_KEY`` env var → ``ark.api_key``
    (fallback ``seedance.api_key``) in secrets.yaml.

    Raises:
        ValueError: If no key can be resolved from any source.
    """
    if explicit_key:
        return explicit_key

    env_key = os.environ.get("ARK_API_KEY", "")
    if env_key:
        return env_key

    file_key = load_ark_key_from_secrets()
    if file_key:
        return file_key

    raise ValueError(
        "ARK_API_KEY not found. Provide it via one of:\n"
        "  1. Constructor argument: SeedanceClient(api_key='...')\n"
        "  2. Environment variable: set ARK_API_KEY=<your-key>\n"
        "  3. config/secrets.yaml: add your key under ark.api_key"
    )


def resolve_seedream_api_key(explicit_key: str | None = None) -> str:
    """Resolve the image (Seedream) Ark API key.

    Priority: explicit arg → ``SEEDREAM_API_KEY`` env var → ``seedream.api_key``
    in secrets.yaml. Deliberately does NOT fall back to the video key, so usage
    stays cleanly separated.

    Raises:
        ValueError: If no key can be resolved from any source.
    """
    if explicit_key:
        return explicit_key

    env_key = os.environ.get("SEEDREAM_API_KEY", "")
    if env_key:
        return env_key

    file_key = load_seedream_key_from_secrets()
    if file_key:
        return file_key

    raise ValueError(
        "SEEDREAM_API_KEY not found. Provide it via one of:\n"
        "  1. Constructor argument: SeedreamClient(api_key='...')\n"
        "  2. Environment variable: set SEEDREAM_API_KEY=<your-key>\n"
        "  3. config/secrets.yaml: add your key under seedream.api_key"
    )
