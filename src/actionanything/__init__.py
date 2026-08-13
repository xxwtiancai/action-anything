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
from .runtime import ActionRuntime
from .schemas import action_plan_schema, action_schema

__all__ = [
    "Action",
    "ActionKind",
    "ActionResult",
    "ActionValidationError",
    "action_plan_schema",
    "action_schema",
    "ActionRuntime",
    "Decision",
    "DryRunExecutor",
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
