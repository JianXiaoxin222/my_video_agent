"""Video Agent Studio workflow engine.

The package is intentionally usable without FastAPI so the graph compiler and
validation helpers can be exercised from the CLI and in unit tests.
"""

from .models import Workflow, WorkflowEdge, WorkflowNode, infer_generation_mode

__all__ = ["Workflow", "WorkflowEdge", "WorkflowNode", "infer_generation_mode"]
