"""Canonical, immutable action and result schemas.

The action schema is the trust boundary between untrusted model/provider output
and policy/executor code.  Validate it here so every caller receives the same
safe, predictable representation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlparse
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


class ActionValidationError(ValueError):
    """Raised when an untrusted action does not match the canonical schema."""


MAX_SELECTOR_LENGTH = 4_096
MAX_TEXT_LENGTH = 50_000
MAX_COORDINATE = 100_000
MAX_SCROLL_DELTA = 10_000
MAX_WAIT_MILLISECONDS = 60_000
MAX_SCREENSHOT_PATH_LENGTH = 240


# A proposal can raise its risk, but cannot lower the baseline set by trusted
# application code.  Applications can still add stricter policies by target,
# session, or business operation.
MINIMUM_RISK: Mapping[ActionKind, RiskLevel] = MappingProxyType(
    {
        ActionKind.NAVIGATE: RiskLevel.READ_ONLY,
        ActionKind.CLICK: RiskLevel.REVERSIBLE,
        ActionKind.TYPE: RiskLevel.REVERSIBLE,
        ActionKind.SCROLL: RiskLevel.NONE,
        ActionKind.WAIT: RiskLevel.NONE,
        ActionKind.SCREENSHOT: RiskLevel.READ_ONLY,
    }
)


def _error(message: str) -> ActionValidationError:
    return ActionValidationError(message)


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(f"{field_name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise _error(f"{field_name} keys must be strings")
    return value


def _freeze_json(value: Any, field_name: str) -> Any:
    """Validate JSON-compatible data and return an immutable deep copy."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _error(f"{field_name} must not contain non-finite numbers")
        return value
    if isinstance(value, Mapping):
        mapping = _require_mapping(value, field_name)
        return MappingProxyType(
            {
                key: _freeze_json(item, f"{field_name}.{key}")
                for key, item in mapping.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, f"{field_name}[{index}]")
            for index, item in enumerate(value)
        )
    raise _error(f"{field_name} must contain JSON-compatible values")


def _thaw_json(value: Any) -> Any:
    """Return a normal JSON-compatible deep copy of a frozen value."""

    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _require_known_keys(
    params: Mapping[str, Any], allowed: set[str], kind: ActionKind
) -> None:
    unknown = sorted(set(params).difference(allowed))
    if unknown:
        joined = ", ".join(repr(key) for key in unknown)
        raise _error(f"{kind.value} does not support parameter(s): {joined}")


def _non_empty_string(value: Any, name: str, maximum: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{name} must be a non-empty string")
    if maximum is not None and len(value) > maximum:
        raise _error(f"{name} must be at most {maximum} characters")
    return value


def _bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise _error(f"{name} must be between {minimum} and {maximum}")
    return value


def _coordinate(value: Any, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(f"{name} must be a finite number")
    if not math.isfinite(float(value)):
        raise _error(f"{name} must be a finite number")
    if not -MAX_COORDINATE <= value <= MAX_COORDINATE:
        raise _error(
            f"{name} must be between {-MAX_COORDINATE} and {MAX_COORDINATE}"
        )
    return value


def _validate_url(value: Any) -> str:
    url = _non_empty_string(value, "navigate.url")
    if any(character.isspace() for character in url):
        raise _error("navigate.url must not contain whitespace")
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
    except ValueError as exc:
        # ``urlparse`` defers some invalid IPv6-bracket errors until the
        # hostname is accessed.  Keep the public intake contract uniform:
        # malformed untrusted input must always produce ActionValidationError.
        raise _error("navigate.url must be a valid HTTP(S) URL") from exc
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise _error("navigate.url must be a valid HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise _error("navigate.url must not include credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise _error("navigate.url must use a valid port") from exc
    if port is not None and not 1 <= port <= 65_535:
        raise _error("navigate.url must use a port between 1 and 65535")
    return url


def _validate_screenshot_path(value: Any) -> str:
    path = _non_empty_string(value, "screenshot.path", MAX_SCREENSHOT_PATH_LENGTH)
    if "\\" in path:
        raise _error("screenshot.path must use a safe relative POSIX path")
    parsed = PurePosixPath(path)
    if (
        parsed.is_absolute()
        or any(part in {".", ".."} for part in parsed.parts)
        or not parsed.name
        or parsed.suffix.lower() != ".png"
    ):
        raise _error("screenshot.path must be a safe relative .png path")
    return path


def _validate_params(kind: ActionKind, raw_params: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one action kind and return its canonical parameter mapping."""

    params = dict(_require_mapping(raw_params, "action params"))

    if kind is ActionKind.NAVIGATE:
        _require_known_keys(params, {"url"}, kind)
        if "url" not in params:
            raise _error("navigate requires parameter 'url'")
        return {"url": _validate_url(params["url"])}

    if kind is ActionKind.CLICK:
        _require_known_keys(params, {"selector", "x", "y", "button"}, kind)
        has_selector = "selector" in params
        has_x = "x" in params
        has_y = "y" in params
        if has_selector == (has_x or has_y):
            raise _error("click requires exactly one target: selector or x and y")
        if has_x != has_y:
            raise _error("click coordinate target requires both x and y")
        normalized: dict[str, Any]
        if has_selector:
            normalized = {
                "selector": _non_empty_string(
                    params["selector"], "click.selector", MAX_SELECTOR_LENGTH
                )
            }
        else:
            normalized = {
                "x": _coordinate(params["x"], "click.x"),
                "y": _coordinate(params["y"], "click.y"),
            }
        if "button" in params:
            button = _non_empty_string(params["button"], "click.button")
            if button not in {"left", "middle", "right"}:
                raise _error("click.button must be left, middle, or right")
            normalized["button"] = button
        return normalized

    if kind is ActionKind.TYPE:
        _require_known_keys(params, {"selector", "text", "press_enter"}, kind)
        if "text" not in params or not isinstance(params["text"], str):
            raise _error("type requires string parameter 'text'")
        if len(params["text"]) > MAX_TEXT_LENGTH:
            raise _error(f"type.text must be at most {MAX_TEXT_LENGTH} characters")
        normalized = {"text": params["text"]}
        if "selector" in params:
            normalized["selector"] = _non_empty_string(
                params["selector"], "type.selector", MAX_SELECTOR_LENGTH
            )
        if "press_enter" in params:
            if not isinstance(params["press_enter"], bool):
                raise _error("type.press_enter must be a boolean")
            normalized["press_enter"] = params["press_enter"]
        return normalized

    if kind is ActionKind.SCROLL:
        _require_known_keys(params, {"delta_x", "delta_y", "x", "y"}, kind)
        has_delta_x = "delta_x" in params
        has_delta_y = "delta_y" in params
        if not has_delta_x and not has_delta_y:
            raise _error("scroll requires delta_x, delta_y, or both")
        normalized = {
            key: _bounded_int(
                params[key], f"scroll.{key}", -MAX_SCROLL_DELTA, MAX_SCROLL_DELTA
            )
            for key in ("delta_x", "delta_y")
            if key in params
        }
        if not any(normalized.values()):
            raise _error("scroll requires a non-zero delta")
        has_x = "x" in params
        has_y = "y" in params
        if has_x != has_y:
            raise _error("scroll position requires both x and y")
        if has_x:
            normalized["x"] = _coordinate(params["x"], "scroll.x")
            normalized["y"] = _coordinate(params["y"], "scroll.y")
        return normalized

    if kind is ActionKind.WAIT:
        _require_known_keys(params, {"milliseconds"}, kind)
        if "milliseconds" not in params:
            raise _error("wait requires parameter 'milliseconds'")
        return {
            "milliseconds": _bounded_int(
                params["milliseconds"],
                "wait.milliseconds",
                0,
                MAX_WAIT_MILLISECONDS,
            )
        }

    if kind is ActionKind.SCREENSHOT:
        _require_known_keys(params, {"path", "full_page"}, kind)
        normalized = {}
        if "path" in params:
            normalized["path"] = _validate_screenshot_path(params["path"])
        if "full_page" in params:
            if not isinstance(params["full_page"], bool):
                raise _error("screenshot.full_page must be a boolean")
            normalized["full_page"] = params["full_page"]
        return normalized

    raise _error(f"unsupported action kind: {kind!r}")


def _coerce_kind(value: Any) -> ActionKind:
    if isinstance(value, ActionKind):
        return value
    if not isinstance(value, str):
        raise _error("action kind must be an ActionKind or string")
    try:
        return ActionKind(value)
    except ValueError as exc:
        raise _error(f"unsupported action kind: {value!r}") from exc


def _coerce_risk(value: Any) -> RiskLevel:
    if isinstance(value, bool) or not isinstance(value, (RiskLevel, int)):
        raise _error("action risk must be an integer RiskLevel")
    try:
        return RiskLevel(value)
    except ValueError as exc:
        raise _error(f"unsupported action risk: {value!r}") from exc


@dataclass(frozen=True)
class Action:
    """An immutable, canonical action proposed by a model or application.

    ``risk`` is an application hint that may make an action stricter, never
    weaker.  The built-in minimum for each action kind is applied at creation.
    """

    kind: ActionKind
    params: Mapping[str, Any] = field(default_factory=dict)
    risk: RiskLevel = RiskLevel.NONE
    id: str = field(default_factory=lambda: uuid4().hex)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise _error("action id must be a non-empty string")
        if len(self.id) > 256:
            raise _error("action id must be at most 256 characters")

        kind = _coerce_kind(self.kind)
        declared_risk = _coerce_risk(self.risk)
        normalized_params = _validate_params(kind, self.params)
        metadata = _freeze_json(_require_mapping(self.metadata, "action metadata"), "metadata")

        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "risk", RiskLevel(max(declared_risk, MINIMUM_RISK[kind])))
        object.__setattr__(self, "params", _freeze_json(normalized_params, "params"))
        object.__setattr__(self, "metadata", metadata)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Action":
        """Build an action from JSON-compatible data with strict validation."""

        payload = _require_mapping(payload, "action payload")
        allowed = {"id", "kind", "params", "risk", "metadata"}
        unknown = sorted(set(payload).difference(allowed))
        if unknown:
            joined = ", ".join(repr(key) for key in unknown)
            raise _error(f"action payload has unsupported field(s): {joined}")
        if "kind" not in payload:
            raise _error("action payload requires 'kind'")
        action_id = payload.get("id", uuid4().hex)
        return cls(
            id=action_id,
            kind=payload["kind"],
            params=payload.get("params", {}),
            risk=payload.get("risk", RiskLevel.NONE),
            metadata=payload.get("metadata", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a normal JSON-compatible deep copy."""

        return {
            "id": self.id,
            "kind": self.kind.value,
            "params": _thaw_json(self.params),
            "risk": int(self.risk),
            "metadata": _thaw_json(self.metadata),
        }


@dataclass(frozen=True)
class ActionResult:
    """The normalized outcome of executing or rejecting one action."""

    action_id: str
    status: ResultStatus
    output: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    audit_error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, str) or not self.action_id.strip():
            raise ValueError("result action_id must be a non-empty string")
        try:
            status = ResultStatus(self.status)
        except ValueError as exc:
            raise ValueError(f"unsupported result status: {self.status!r}") from exc
        output = _freeze_json(_require_mapping(self.output, "result output"), "output")
        if self.error is not None and not isinstance(self.error, str):
            raise TypeError("result error must be a string or None")
        if self.audit_error is not None and not isinstance(self.audit_error, str):
            raise TypeError("result audit_error must be a string or None")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "output", output)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "status": self.status.value,
            "output": _thaw_json(self.output),
            "error": self.error,
            "audit_error": self.audit_error,
        }
