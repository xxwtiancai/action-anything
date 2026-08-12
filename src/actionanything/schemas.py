"""Versioned JSON Schema documents for portable ActionAnything inputs.

These documents help a caller constrain structured model output before it
reaches :class:`~actionanything.actions.Action`.  They intentionally do not
replace canonical Python validation, policy evaluation, human confirmation, or
executor containment.  The runtime remains the final authority because JSON
Schema cannot express every semantic and environment-dependent boundary.
"""

from __future__ import annotations

from typing import Any

from .actions import (
    MAX_COORDINATE,
    MAX_SCREENSHOT_PATH_LENGTH,
    MAX_SCROLL_DELTA,
    MAX_SELECTOR_LENGTH,
    MAX_TEXT_LENGTH,
    MAX_WAIT_MILLISECONDS,
    ActionKind,
    RiskLevel,
)


JSON_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
ACTION_SCHEMA_ID = "urn:actionanything:action:v1"
ACTION_PLAN_SCHEMA_ID = "urn:actionanything:action-plan:v1"


def _non_empty_string_schema(maximum: int) -> dict[str, Any]:
    """Return the shared contract for a non-whitespace bounded string."""

    return {
        "type": "string",
        "minLength": 1,
        "maxLength": maximum,
        "pattern": r"\S",
    }


def _definitions() -> dict[str, Any]:
    """Build definitions shared by both public schema documents.

    This deliberately builds a new tree for every export.  Consumers may
    freely annotate or transform a returned document without changing a later
    call to :func:`action_schema` or :func:`action_plan_schema`.
    """

    selector = _non_empty_string_schema(MAX_SELECTOR_LENGTH)
    coordinate = {
        "type": "number",
        "minimum": -MAX_COORDINATE,
        "maximum": MAX_COORDINATE,
    }

    definitions: dict[str, Any] = {
        "jsonValue": {
            "description": "A finite JSON value for untrusted metadata.",
            "anyOf": [
                {"type": "null"},
                {"type": "boolean"},
                {"type": "string"},
                {"type": "number"},
                {
                    "type": "array",
                    "items": {"$ref": "#/$defs/jsonValue"},
                },
                {
                    "type": "object",
                    "additionalProperties": {"$ref": "#/$defs/jsonValue"},
                },
            ],
        },
        "navigateParams": {
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {
                    "type": "string",
                    "minLength": 1,
                    "allOf": [
                        {"pattern": r"^[Hh][Tt][Tt][Pp][Ss]?://\S+$"},
                        {"not": {"pattern": r"\s"}},
                    ],
                    "$comment": (
                        "Canonical Action validation additionally checks host, "
                        "credentials, port syntax, and the JSON-integer subset."
                    ),
                }
            },
            "additionalProperties": False,
        },
        "clickParams": {
            "type": "object",
            "properties": {
                "selector": selector,
                "x": coordinate,
                "y": coordinate,
                "button": {"enum": ["left", "middle", "right"]},
            },
            "additionalProperties": False,
            "oneOf": [
                {
                    "required": ["selector"],
                    "not": {
                        "anyOf": [{"required": ["x"]}, {"required": ["y"]}]
                    },
                },
                {
                    "required": ["x", "y"],
                    "not": {"required": ["selector"]},
                },
            ],
        },
        "typeParams": {
            "type": "object",
            "required": ["text"],
            "properties": {
                "selector": selector,
                "text": {"type": "string", "maxLength": MAX_TEXT_LENGTH},
                "press_enter": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "scrollParams": {
            "type": "object",
            "properties": {
                "delta_x": {
                    "type": "integer",
                    "minimum": -MAX_SCROLL_DELTA,
                    "maximum": MAX_SCROLL_DELTA,
                },
                "delta_y": {
                    "type": "integer",
                    "minimum": -MAX_SCROLL_DELTA,
                    "maximum": MAX_SCROLL_DELTA,
                },
                "x": coordinate,
                "y": coordinate,
            },
            "additionalProperties": False,
            "allOf": [
                {
                    "anyOf": [
                        {"required": ["delta_x"]},
                        {"required": ["delta_y"]},
                    ]
                },
                {
                    "anyOf": [
                        {
                            "required": ["delta_x"],
                            "properties": {"delta_x": {"not": {"const": 0}}},
                        },
                        {
                            "required": ["delta_y"],
                            "properties": {"delta_y": {"not": {"const": 0}}},
                        },
                    ]
                },
                {"if": {"required": ["x"]}, "then": {"required": ["y"]}},
                {"if": {"required": ["y"]}, "then": {"required": ["x"]}},
            ],
        },
        "waitParams": {
            "type": "object",
            "required": ["milliseconds"],
            "properties": {
                "milliseconds": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": MAX_WAIT_MILLISECONDS,
                }
            },
            "additionalProperties": False,
        },
        "screenshotParams": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_SCREENSHOT_PATH_LENGTH,
                    "allOf": [
                        {"pattern": r"^[^\\]+\.[Pp][Nn][Gg]$"},
                        {"not": {"pattern": r"[\r\n]"}},
                        {"not": {"pattern": r"^/"}},
                        {"not": {"pattern": r"(?:^|/)\.\.($|/)"}},
                    ],
                },
                "full_page": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    }

    parameter_definitions = {
        ActionKind.NAVIGATE: "navigateParams",
        ActionKind.CLICK: "clickParams",
        ActionKind.TYPE: "typeParams",
        ActionKind.SCROLL: "scrollParams",
        ActionKind.WAIT: "waitParams",
        ActionKind.SCREENSHOT: "screenshotParams",
    }
    conditions: list[dict[str, Any]] = []
    for kind, definition in parameter_definitions.items():
        then: dict[str, Any] = {
            "properties": {"params": {"$ref": f"#/$defs/{definition}"}}
        }
        if kind is not ActionKind.SCREENSHOT:
            then["required"] = ["params"]
        conditions.append(
            {
                "if": {
                    "properties": {"kind": {"const": kind.value}},
                    "required": ["kind"],
                },
                "then": then,
            }
        )

    definitions["action"] = {
        "title": "ActionAnything Action v1",
        "description": (
            "One normalized action proposal. Runtime validation remains "
            "authoritative."
        ),
        "type": "object",
        "required": ["kind"],
        "properties": {
            "id": _non_empty_string_schema(256),
            "kind": {"enum": [kind.value for kind in ActionKind]},
            "params": {"type": "object"},
            "risk": {"type": "integer", "enum": [int(level) for level in RiskLevel]},
            "metadata": {
                "type": "object",
                "additionalProperties": {"$ref": "#/$defs/jsonValue"},
            },
        },
        "additionalProperties": False,
        "allOf": conditions,
        "$comment": (
            "A declared risk is an untrusted hint: Action canonicalization applies "
            "the built-in minimum risk for the action kind."
        ),
    }
    return definitions


def action_schema() -> dict[str, Any]:
    """Return a fresh Draft 2020-12 schema for one ActionAnything action.

    The document is versioned by :data:`ACTION_SCHEMA_ID`.  A later breaking
    wire-contract change must use a new schema version rather than mutating
    this one in place.
    """

    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "$id": ACTION_SCHEMA_ID,
        "title": "ActionAnything Action v1",
        "$ref": "#/$defs/action",
        "$defs": _definitions(),
    }


def action_plan_schema() -> dict[str, Any]:
    """Return a fresh Draft 2020-12 schema for a portable action plan.

    A plan may be a bare JSON list or an object containing an ``actions`` list.
    The object envelope intentionally remains open for application-owned
    metadata. Its fields are not policy or execution configuration.
    """

    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "$id": ACTION_PLAN_SCHEMA_ID,
        "title": "ActionAnything Action Plan v1",
        "description": "A portable list of normalized ActionAnything action proposals.",
        "oneOf": [
            {"type": "array", "items": {"$ref": "#/$defs/action"}},
            {
                "type": "object",
                "required": ["actions"],
                "properties": {
                    "actions": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/action"},
                    }
                },
                "additionalProperties": True,
            },
        ],
        "$defs": _definitions(),
    }
