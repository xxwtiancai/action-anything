"""ActionAnything: safe execution primitives for AI agent actions."""

from .actions import Action, ActionKind, ActionResult, ResultStatus, RiskLevel
from .executors import DryRunExecutor, PlaywrightExecutor
from .policy import Decision, PolicyEngine, PolicyOutcome
from .recorder import TraceRecorder, read_trace
from .runtime import ActionRuntime

__all__ = [
    "Action",
    "ActionKind",
    "ActionResult",
    "ActionRuntime",
    "Decision",
    "DryRunExecutor",
    "PlaywrightExecutor",
    "PolicyEngine",
    "PolicyOutcome",
    "ResultStatus",
    "RiskLevel",
    "TraceRecorder",
    "read_trace",
]

__version__ = "0.1.0"
