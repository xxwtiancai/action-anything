"""Model-agnostic action and result schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Mapping
from uuid import uuid4


class ActionKind(str, Enum):
    """Actions understood by the built-in executors."""

    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SCROLL = "scroll"
    WAIT = "wait"
    SCREENSHOT = "screenshot"


class RiskLevel(IntEnum):
    """Increasing levels of action side effects."""

    NONE = 0
    READ_ONLY = 1
    REVERSIBLE = 2
    EXTERNAL = 3
    CRITICAL = 4


class ResultStatus(str, Enum):
    """Possible terminal states for one action."""

    SUCCESS = "success"
    ERROR = "error"
    DENIED = "denied"
    CANCELLED = "cancelled"
    DRY_RUN = "dry_run"


@dataclass(frozen=True)
class Action:
    """A normalized action proposed by a model or application."""

    kind: ActionKind
    params: Mapping[str, Any] = field(default_factory=dict)
    risk: RiskLevel = RiskLevel.NONE
    id: str = field(default_factory=lambda: uuid4().hex)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("action id must not be empty")
        if not isinstance(self.params, Mapping):
            raise TypeError("action params must be a mapping")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("action metadata must be a mapping")

        object.__setattr__(self, "params", dict(self.params))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Action":
        """Build an action from JSON-compatible data with strict enum parsing."""

        if "kind" not in payload:
            raise ValueError("action payload requires 'kind'")
        return cls(
            id=str(payload.get("id") or uuid4().hex),
            kind=ActionKind(str(payload["kind"])),
            params=payload.get("params") or {},
            risk=RiskLevel(int(payload.get("risk", RiskLevel.NONE))),
            metadata=payload.get("metadata") or {},
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        return {
            "id": self.id,
            "kind": self.kind.value,
            "params": dict(self.params),
            "risk": int(self.risk),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ActionResult:
    """The normalized outcome of executing or rejecting an action."""

    action_id: str
    status: ResultStatus
    output: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "status": self.status.value,
            "output": dict(self.output),
            "error": self.error,
        }
