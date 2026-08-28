from __future__ import annotations

from dataclasses import dataclass, field

from ..executor import WorkflowExecutor
from ..repository import StudioRepository


@dataclass
class ApiContext:
    """State shared by handlers for one FastAPI application instance."""

    repository: StudioRepository
    executor: WorkflowExecutor
    confirmation_tokens: dict[str, str] = field(default_factory=dict)

