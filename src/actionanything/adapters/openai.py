"""Adapter for OpenAI Responses API ``computer_call`` output items.

A Responses computer call contains one ``action`` plus its ``id``, ``call_id``,
``status``, and ``pending_safety_checks``.  This adapter intentionally accepts
only completed calls with no pending safety checks; it never acknowledges a
safety check or sends a provider request.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..actions import Action, ActionKind, ActionValidationError
from .base import AdapterCapabilities, AdapterError


class OpenAIComputerUseAdapter:
    """Normalize one supported OpenAI computer call into a canonical action.

    Supported provider actions are click, type, scroll, wait, and screenshot.
    Unsupported actions such as drag, move, keypress, and double-click raise an
    error instead of being silently approximated. The application remains
    responsible for model calls, screenshots sent back to the model, policies,
    and executor lifecycle.
    """

    capabilities = AdapterCapabilities(
        action_kinds=frozenset(
            {
                ActionKind.CLICK,
                ActionKind.TYPE,
                ActionKind.SCROLL,
                ActionKind.WAIT,
                ActionKind.SCREENSHOT,
            }
        ),
        coordinate_click=True,
        focused_type=True,
    )

    _WAIT_MILLISECONDS = 2_000
    _ITEM_FIELDS = frozenset(
        {
            "type",
            "id",
            "call_id",
            "status",
            "pending_safety_checks",
            "action",
        }
    )

    def adapt(self, item: Mapping[str, Any]) -> list[Action]:
        """Parse one safe, completed ``computer_call`` item into an action."""

        if not isinstance(item, Mapping):
            raise AdapterError("OpenAI computer call must be a mapping")
        self._unknown_fields("computer_call", item, self._ITEM_FIELDS)
        if item.get("type") != "computer_call":
            raise AdapterError("expected an OpenAI computer_call item")
        item_id = self._required_non_empty_string(item, "id")
        call_id = self._required_non_empty_string(item, "call_id")
        if item.get("status") != "completed":
            raise AdapterError("OpenAI computer_call must have completed status")

        pending_safety_checks = item.get("pending_safety_checks")
        if not isinstance(pending_safety_checks, list):
            raise AdapterError(
                "OpenAI computer_call requires pending_safety_checks to be a list"
            )
        if pending_safety_checks:
            raise AdapterError(
                "OpenAI computer_call has pending safety checks and requires "
                "an application safety-review flow"
            )

        raw_action = item.get("action")
        if not isinstance(raw_action, Mapping):
            raise AdapterError("OpenAI computer_call action must be a mapping")
        action_type = raw_action.get("type")
        if not isinstance(action_type, str) or not action_type:
            raise AdapterError("OpenAI computer_call action requires a non-empty string type")

        metadata = {
            "provider": "openai",
            "provider_item_id": item_id,
            "provider_call_id": call_id,
            "provider_action_type": action_type,
        }
        try:
            return [self._adapt_action(action_type, raw_action, metadata)]
        except ActionValidationError as exc:
            # Validation errors can include a caller-provided value (for
            # example an over-long selector). Do not reflect that provider
            # data into an exception that might later enter an application log.
            raise AdapterError("invalid OpenAI computer action parameters") from exc

    @staticmethod
    def _required_non_empty_string(item: Mapping[str, Any], field: str) -> str:
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            raise AdapterError(f"OpenAI computer_call requires a non-empty {field}")
        return value

    @staticmethod
    def _unknown_fields(
        subject: str, payload: Mapping[str, Any], allowed: set[str] | frozenset[str]
    ) -> None:
        if any(not isinstance(key, str) for key in payload):
            raise AdapterError(f"OpenAI {subject} field names must be strings")
        unknown = sorted(set(payload).difference(allowed))
        if unknown:
            raise AdapterError(f"OpenAI {subject} has unsupported field(s)")

    def _adapt_action(
        self,
        action_type: str,
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> Action:
        if action_type == "click":
            self._unknown_fields(
                f"{action_type!r} action", payload, {"type", "x", "y", "button"}
            )
            if "button" not in payload:
                raise AdapterError("OpenAI 'click' action requires button")
            return Action(
                ActionKind.CLICK,
                {
                    "x": payload.get("x"),
                    "y": payload.get("y"),
                    "button": payload.get("button"),
                },
                metadata=metadata,
            )
        if action_type == "type":
            self._unknown_fields(f"{action_type!r} action", payload, {"type", "text"})
            return Action(
                ActionKind.TYPE,
                {"text": payload.get("text")},
                metadata=metadata,
            )
        if action_type == "scroll":
            self._unknown_fields(
                f"{action_type!r} action",
                payload,
                {"type", "x", "y", "scroll_x", "scroll_y"},
            )
            return Action(
                ActionKind.SCROLL,
                {
                    "x": payload.get("x"),
                    "y": payload.get("y"),
                    "delta_x": payload.get("scroll_x"),
                    "delta_y": payload.get("scroll_y"),
                },
                metadata=metadata,
            )
        if action_type == "wait":
            self._unknown_fields(f"{action_type!r} action", payload, {"type"})
            return Action(
                ActionKind.WAIT,
                {"milliseconds": self._WAIT_MILLISECONDS},
                metadata=metadata,
            )
        if action_type == "screenshot":
            self._unknown_fields(f"{action_type!r} action", payload, {"type"})
            return Action(ActionKind.SCREENSHOT, metadata=metadata)
        raise AdapterError(
            "unsupported OpenAI computer action type; "
            "upgrade the adapter or handle it explicitly"
        )
