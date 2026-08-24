"""YAML configuration loader with environment variable substitution.

Supports ${VAR_NAME} patterns in config values, resolved from os.environ.
"""

import os
import re
from pathlib import Path
from typing import Any

import yaml

# Matches ${VAR_NAME} or ${VAR_NAME:default_value}
_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")


def _resolve_env(value: Any) -> Any:
    """Resolve ${VAR_NAME} patterns in a string value, recursively on dicts/lists."""
    if isinstance(value, str):
        def _replace(match: re.Match) -> str:
            var_name = match.group(1)
            default = match.group(2)
            if default is not None:
                return os.environ.get(var_name, default)
            resolved = os.environ.get(var_name)
            if resolved is None:
                raise KeyError(
                    f"Environment variable '{var_name}' is not set "
                    f"and no default is provided. "
                    f"Hint: export {var_name}=<value>"
                )
            return resolved
        return _ENV_VAR_PATTERN.sub(_replace, value)
    elif isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env(item) for item in value]
    return value


def load_config(config_path: str | Path) -> dict:
    """Load a YAML config file and resolve environment variable references.

    Args:
        config_path: Path to a .yaml config file (relative to project root or absolute).

    Returns:
        Parsed config dict with ${VAR_NAME} patterns resolved.

    Raises:
        FileNotFoundError: If config_path does not exist.
        KeyError: If an env var reference has no default and the var is not set.
    """
    config_path = Path(config_path)
    if not config_path.is_absolute():
        # Resolve relative to project root (two levels up from this file)
        project_root = Path(__file__).resolve().parent.parent.parent
        config_path = project_root / config_path

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        return {}

    return _resolve_env(data)


def load_config_or_default(config_path: str | Path, default: dict | None = None) -> dict:
    """Load config file, returning default if not found (no exception)."""
    try:
        return load_config(config_path)
    except FileNotFoundError:
        if default is not None:
            return default
        raise
