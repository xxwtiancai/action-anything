"""Shared protocol and errors for provider-to-action adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from ..actions import Action, ActionKind


class AdapterError(ValueError):
    """Raised when an adapter cannot safely normalize provider output."""


@dataclass(frozen=True)
class AdapterCapabilities:
    """A declared subset of the canonical action surface an adapter can emit."""

    action_kinds: frozenset[ActionKind]
    coordinate_click: bool = False
    focused_type: bool = False


class ActionAdapter(Protocol):
    """Normalize one provider output item without performing network I/O."""

    capabilities: AdapterCapabilities

    def adapt(self, item: Mapping[str, Any]) -> list[Action]:
        """Return canonical actions or raise ``AdapterError`` without fallback."""
