"""ActionAnything: safe execution primitives for AI agent actions."""

from .actions import (
    Action,
    ActionKind,
    ActionResult,
    ActionValidationError,
    ResultStatus,
    RiskLevel,
)
from .executors import DryRunExecutor, ExecutorSafetyError, PlaywrightExecutor
from .policy import Decision, PolicyEngine, PolicyOutcome
from .recorder import TraceRecorder, read_trace
from .runtime import ActionRuntime, ExecutionBudget

__all__ = [
    "Action",
    "ActionKind",
    "ActionResult",
    "ActionValidationError",
    "ActionRuntime",
    "Decision",
    "DryRunExecutor",
    "ExecutionBudget",
    "ExecutorSafetyError",
    "PlaywrightExecutor",
    "PolicyEngine",
    "PolicyOutcome",
    "ResultStatus",
    "RiskLevel",
    "TraceRecorder",
    "read_trace",
]

__version__ = "0.1.0"
