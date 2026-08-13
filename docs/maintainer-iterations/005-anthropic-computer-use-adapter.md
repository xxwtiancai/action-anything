# 005 · Strict Anthropic Computer Use adapter

**Status:** completed locally; pending independent review and remote CI

## Observation

Anthropic Computer Use offers a wider, versioned action surface than
ActionAnything's canonical action contract. A returned `tool_use` block does
not carry the computer-tool version or a trustworthy display-size binding, and
some provider actions use executor-specific semantics.

## Falsifiable hypothesis

If the repository normalizes only a direct, explicitly version-bound subset
whose parameters have an unambiguous canonical meaning, applications can use
Anthropic Computer Use output without silently expanding ActionAnything's
execution surface.

## Small scope

- Added `AnthropicComputerUseAdapter` with trusted `tool_version`, display
  width, and display height constructor configuration.
- Accepted one ordinary-direct `tool_use` block only, with exact field
  validation. Omitted or `null` callers remain compatible; a non-empty caller
  must be exactly `direct`.
- Mapped coordinate left/right/middle clicks, focused text entry, whole-
  millisecond waits, and screenshots.
- Rejected scrolling because Anthropic's wheel-repeat amount has no proven
  lossless mapping to the executor's wheel delta; also rejected keys, mouse
  movement, drag, multi-click, button-down/up, hold, zoom, programmatic
  callers, and unknown fields.
- Added offline adapter tests and public boundary documentation.

## Deliberate non-goals

No Anthropic SDK, network request, API key, agent loop, screenshot return,
coordinate scaling, provider-safety acknowledgement, executor change, or
policy-default change was added. The embedding application still binds each
response to its model request, handles provider workflows, and runs local
policy and confirmation.

## Verification

Run locally with the repository's Python 3.12 runtime:

```bash
PYTHONPATH=src python3 -m unittest tests.test_adapters -v
git diff --check
```

Actual result: 21 adapter tests passed, including successful mappings,
constructor/configuration bounds, caller handling, malformed and
unsupported input rejection, secret non-reflection in adapter errors, and
provenance minimization. The wait cases also accept negligible binary-float
representation noise around a whole millisecond while rejecting a genuinely
fractional millisecond. `git diff --check` passed.

## Residual risk and next question

The application, not the adapter, must ensure that the configured display
dimensions match the coordinate space of the screenshot and executor. The
adapter cannot prove model intent, webpage semantics, provider-side safety
state, or browser isolation; local policy, human confirmation, an allowlist,
and isolated execution remain necessary.

The next independently reviewed question is whether any unsupported provider
action has an executor-agnostic, lossless mapping. In particular, do not add
Anthropic scroll support until its units can be defined and tested against the
target executor without a guessed conversion factor.

## Source checked

The [Anthropic Computer Use documentation](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)
was checked in 2026-08. It documents the versioned tool definitions, direct
application execution responsibility, action surface, and isolation/HITL
guidance used to constrain this iteration.
