"""Strict adapter for Anthropic Computer Use ``tool_use`` blocks.

The version and display geometry of Anthropic's computer tool are request
configuration, not fields on a returned ``tool_use`` block.  The embedding
application therefore supplies them as trusted constructor arguments and must
bind each block to the matching request.  This module performs no provider I/O
and intentionally accepts only the documented action subset that maps exactly
to ActionAnything's canonical actions.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from ..actions import (
    MAX_COORDINATE,
    MAX_WAIT_MILLISECONDS,
    Action,
    ActionKind,
    ActionValidationError,
)
from .base import AdapterCapabilities, AdapterError


class AnthropicComputerUseAdapter:
    """Normalize one direct Anthropic Computer Use block into one action.

    ``tool_version`` and display dimensions are trusted application
    configuration. In particular, this adapter never infers viewport scaling
    from model output. It supports the common documented subset of
    ``computer_20250124`` and ``computer_20251124``: coordinate clicks,
    focused typing, waiting, and screenshots.

    Key presses, drag gestures, multi-clicks, zoom, programmatic callers, and
    all unknown fields raise :class:`AdapterError` rather than being silently
    approximated.  The embedding application still owns model calls, provider
    safety flows, screenshots returned to a model, and its local policy and
    confirmation lifecycle.
    """

    capabilities = AdapterCapabilities(
        action_kinds=frozenset(
            {
                ActionKind.CLICK,
                ActionKind.TYPE,
                ActionKind.WAIT,
                ActionKind.SCREENSHOT,
            }
        ),
        coordinate_click=True,
        focused_type=True,
    )

    _SUPPORTED_TOOL_VERSIONS = frozenset(
        {"computer_20250124", "computer_20251124"}
    )
    _ITEM_FIELDS = frozenset({"type", "id", "name", "input", "caller"})
    _DIRECT_CALLER_FIELDS = frozenset({"type"})
    _CLICK_BUTTONS = {
        "left_click": "left",
        "right_click": "right",
        "middle_click": "middle",
    }

    def __init__(
        self,
        *,
        tool_version: str,
        display_width_px: int,
        display_height_px: int,
    ) -> None:
        """Create a normalizer bound to one trusted Anthropic tool config.

        The embedding application supplies dimensions from the computer-tool
        definition used for the matching model request.
        """

        if (
            not isinstance(tool_version, str)
            or tool_version not in self._SUPPORTED_TOOL_VERSIONS
        ):
            raise ValueError("unsupported Anthropic computer tool version")
        self.tool_version = tool_version
        self.display_width_px = self._trusted_positive_int(
            display_width_px, "display_width_px", maximum=MAX_COORDINATE
        )
        self.display_height_px = self._trusted_positive_int(
            display_height_px, "display_height_px", maximum=MAX_COORDINATE
        )

    def adapt(self, item: Mapping[str, Any]) -> list[Action]:
        """Parse one direct ``tool_use`` block without fallback behavior."""

        if not isinstance(item, Mapping):
            raise AdapterError("Anthropic tool_use block must be a mapping")
        self._unknown_fields(item, self._ITEM_FIELDS, "tool_use block")
        if item.get("type") != "tool_use":
            raise AdapterError("expected an Anthropic tool_use block")
        tool_use_id = self._required_non_empty_string(item, "id")
        if item.get("name") != "computer":
            raise AdapterError("expected an Anthropic computer tool_use block")
        self._validate_caller(item)

        payload = item.get("input")
        if not isinstance(payload, Mapping):
            raise AdapterError("Anthropic computer input must be a mapping")
        action_type = payload.get("action")
        if not isinstance(action_type, str) or not action_type:
            raise AdapterError("Anthropic computer input requires a non-empty action")

        metadata = {
            "provider": "anthropic",
            "provider_item_id": tool_use_id,
            "provider_tool_name": "computer",
            "provider_tool_version": self.tool_version,
            "provider_action_type": action_type,
        }
        try:
            return [self._adapt_action(action_type, payload, metadata)]
        except ActionValidationError:
            # An Action validation error can include an untrusted parameter.
            # Preserve the safe exception boundary for callers and logs.
            raise AdapterError("invalid Anthropic computer action parameters") from None

    def _adapt_action(
        self,
        action_type: str,
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> Action:
        if action_type in self._CLICK_BUTTONS:
            self._unknown_fields(payload, {"action", "coordinate"}, "computer input")
            x, y = self._coordinate(payload.get("coordinate"))
            return Action(
                ActionKind.CLICK,
                {"x": x, "y": y, "button": self._CLICK_BUTTONS[action_type]},
                metadata=metadata,
            )
        if action_type == "type":
            self._unknown_fields(payload, {"action", "text"}, "computer input")
            return Action(
                ActionKind.TYPE,
                {"text": payload.get("text")},
                metadata=metadata,
            )
        if action_type == "wait":
            self._unknown_fields(payload, {"action", "duration"}, "computer input")
            return Action(
                ActionKind.WAIT,
                {"milliseconds": self._milliseconds(payload.get("duration"))},
                metadata=metadata,
            )
        if action_type == "screenshot":
            self._unknown_fields(payload, {"action"}, "computer input")
            return Action(ActionKind.SCREENSHOT, metadata=metadata)
        raise AdapterError(
            "unsupported Anthropic computer action; upgrade the adapter or handle it explicitly"
        )

    @staticmethod
    def _trusted_positive_int(value: Any, field: str, *, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field} must be an integer")
        if not 1 <= value <= maximum:
            raise ValueError(f"{field} must be between 1 and {maximum}")
        return value

    @staticmethod
    def _required_non_empty_string(item: Mapping[str, Any], field: str) -> str:
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            raise AdapterError(f"Anthropic tool_use block requires a non-empty {field}")
        return value

    def _validate_caller(self, item: Mapping[str, Any]) -> None:
        """Accept ordinary direct blocks and reject indirect tool callers.

        SDK response shapes can omit ``caller`` or serialize its optional
        value as ``null`` for traditional direct tool use. A non-empty caller
        must use the explicit direct shape; a code-execution caller belongs to
        a different application lifecycle and is rejected here.
        """

        caller = item.get("caller")
        if caller is None:
            return
        if not isinstance(caller, Mapping):
            raise AdapterError("Anthropic tool_use caller must be a direct mapping")
        self._unknown_fields(caller, self._DIRECT_CALLER_FIELDS, "tool_use caller")
        if caller.get("type") != "direct":
            raise AdapterError("Anthropic tool_use caller must be direct")

    def _coordinate(self, value: Any) -> tuple[int, int]:
        if not isinstance(value, list) or len(value) != 2:
            raise AdapterError("Anthropic computer coordinate must be a two-item list")
        x, y = value
        if (
            isinstance(x, bool)
            or isinstance(y, bool)
            or not isinstance(x, int)
            or not isinstance(y, int)
        ):
            raise AdapterError("Anthropic computer coordinate must contain integers")
        if not 0 <= x < self.display_width_px or not 0 <= y < self.display_height_px:
            raise AdapterError("Anthropic computer coordinate is outside the configured display")
        return x, y

    @staticmethod
    def _milliseconds(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AdapterError("Anthropic wait duration must be a finite number")
        if isinstance(value, int):
            if not 0 <= value <= MAX_WAIT_MILLISECONDS // 1_000:
                raise AdapterError("Anthropic wait duration is outside the supported range")
            return value * 1_000

        if not math.isfinite(value):
            raise AdapterError("Anthropic wait duration must be a finite number")
        if not 0 <= value <= MAX_WAIT_MILLISECONDS / 1_000:
            raise AdapterError("Anthropic wait duration is outside the supported range")
        milliseconds_float = value * 1_000
        if not math.isfinite(milliseconds_float):
            raise AdapterError("Anthropic wait duration is outside the supported range")
        milliseconds = round(milliseconds_float)
        # JSON decoders expose provider durations as binary floats. Permit
        # negligible representation noise around a whole millisecond, but do
        # not approximate a provider-supplied fractional millisecond.
        if abs(milliseconds_float - milliseconds) > 1e-9:
            raise AdapterError("Anthropic wait duration must resolve to whole milliseconds")
        if not 0 <= milliseconds <= MAX_WAIT_MILLISECONDS:
            raise AdapterError("Anthropic wait duration is outside the supported range")
        return milliseconds

    @staticmethod
    def _unknown_fields(
        payload: Mapping[str, Any],
        allowed: set[str] | frozenset[str],
        subject: str,
    ) -> None:
        if any(not isinstance(key, str) for key in payload):
            raise AdapterError(f"Anthropic {subject} field names must be strings")
        if set(payload).difference(allowed):
            raise AdapterError(f"Anthropic {subject} has unsupported field(s)")
