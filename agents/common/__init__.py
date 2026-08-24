"""Shared utilities used across all agents: paths, config, LLM clients."""

from pathlib import Path

# Absolute path to the project root (video_agent/).
# agents/common/__init__.py -> parents[0]=common, [1]=agents, [2]=root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
