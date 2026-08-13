# ActionAnything

> A policy-gated action layer for AI-directed work.

ActionAnything is a model-agnostic runtime for evaluating, approving,
executing, recording, and replaying normalized AI-directed actions. It provides
a small, auditable layer between an application-provided action proposal and an
executor that may interact with a browser or other application environment.
The embedding application owns model calls, prompts, credentials, browser
profiles, and deployment isolation.

## What works today

- A model-agnostic schema for navigation, click, type, scroll, wait, and screenshot actions.
- Strict OpenAI Responses and Anthropic Computer Use adapters that normalize a
  documented action subset without making model calls.
- A composable policy engine with risk gates, domain and exact-selector allowlists, and sensitive-target checks.
- Trusted per-batch execution budgets for action count and cumulative wait time.
- Human confirmation for actions that the configured policy gates.
- A zero-dependency dry-run executor and an optional Playwright browser executor.
- Redacted JSONL traces plus trace inspection and replay for local test data.
- A small `aa` CLI for running portable JSON action plans and exporting their
  machine-readable contracts.

## Quick start

```bash
git clone https://github.com/xxwtiancai/action-anything.git
cd action-anything
python3 -m pip install -e .
aa run examples/demo.json --allowed-domain example.com
aa inspect actionanything-trace.jsonl
```

Dry-run is the default: no real browser action occurs unless `--execute` is
provided. To enable the Playwright executor:

```bash
python3 -m pip install -e '.[browser]'
playwright install chromium
aa run examples/demo.json --allowed-domain example.com --execute
```

## Python API

```python
from actionanything import (
    Action,
    ActionKind,
    ActionRuntime,
    DryRunExecutor,
    PolicyEngine,
)

# Navigation needs an explicit allowlist even in dry-run. The same policy can
# later be paired with an explicitly enabled real executor.
runtime = ActionRuntime(
    DryRunExecutor(),
    policy=PolicyEngine.standard(["example.com"]),
)
result = runtime.execute(
    Action(ActionKind.NAVIGATE, {"url": "https://example.com"})
)
print(result.to_dict())
```

## Use structured output contracts

ActionAnything exports self-contained, versioned [JSON Schema Draft
2020-12](https://json-schema.org/draft/2020-12) documents for model structured
output, form generation, and offline input checks:

```bash
aa schema action > actionanything-action-v1.schema.json
aa schema plan > actionanything-plan-v1.schema.json
```

The Python API returns a fresh JSON-serializable document on every call:

```python
from actionanything import action_plan_schema, action_schema

one_action_contract = action_schema()
portable_plan_contract = action_plan_schema()
```

The schemas describe input shape only. They do not replace canonical `Action`
validation, risk floors, policy evaluation, human confirmation, domain
allowlisting, or executor containment. In particular, a model-provided
`risk` is never an authority to lower the runtime's minimum risk.

Some runtime rules are intentionally stricter than portable JSON Schema. For
example, Python validation distinguishes an integer JSON token from `1.0` for
bounded integer fields, performs full URL and artifact-path parsing, and
limits action metadata to 64 mapping/list/tuple containers with no circular
references. This is a runtime recursion boundary, not a general plan-size or
key-count quota. Send all accepted output through `Action.from_dict()` or
`Action(...)` before it is evaluated or executed.

## Provider adapters

Adapters are parsing boundaries, not provider clients: your application makes
the model request, binds the returned payload to its own trusted request
configuration, runs local policy/confirmation, executes a permitted action,
and returns any tool result or screenshot. For example, the Anthropic adapter
accepts one direct `tool_use` block. The application must configure its tool
version and display dimensions to match the request that produced the block:

```python
from actionanything.adapters import AnthropicComputerUseAdapter

adapter = AnthropicComputerUseAdapter(
    tool_version="computer_20250124",
    display_width_px=1024,
    display_height_px=768,
)
action = adapter.adapt(
    {
        "type": "tool_use",
        "id": "toolu_example",
        "name": "computer",
        "caller": {"type": "direct"},
        "input": {"action": "left_click", "coordinate": [405, 157]},
    }
)[0]
```

It maps only coordinate left/right/middle clicks, focused `type`, bounded
`wait`, and `screenshot`. Omitted or `null` `caller` values preserve ordinary
direct-tool compatibility; any non-empty caller must be exactly
`{"type": "direct"}`. It rejects scrolling, key presses, drag/multi-click
gestures, zoom, programmatic callers, and unknown fields rather than guessing
their semantics. The adapter does not treat provider-side safeguards as local
approval; use `PolicyEngine` and an application-owned confirmation flow before
execution.

### Exact selector allowlists

For a fixed page workflow, add an opt-in exact selector boundary for `click`
and `type` actions. It compares trusted original locator text byte-for-byte
and still requires confirmation on a match; it does not parse or normalize CSS
or other executor locator syntaxes, and it is not a claim that the matched
element is business-safe.

```python
policy = PolicyEngine.standard(
    ["example.com"],
    allowed_selectors={"#search", "input[name=query]"},
)
```

When installed, it denies coordinate clicks and focused-input typing because
they have no selector to compare. That intentionally means coordinate-click
and focused-type provider outputs need a different, explicitly reviewed policy
configuration. It does not prove selector uniqueness, page state, DOM
stability, click effects, or cross-domain safety; retain confirmation and the
executor domain boundary.

## Bound a plan

Plans remain portable data, not policy. Put a trusted budget in the application
or CLI invocation rather than accepting it from model-generated JSON:

```python
from actionanything import ExecutionBudget

results = runtime.execute_many(
    [
        Action(ActionKind.WAIT, {"milliseconds": 500}),
        Action(ActionKind.WAIT, {"milliseconds": 500}),
    ],
    budget=ExecutionBudget(
        max_actions=10,
        max_total_wait_milliseconds=30_000,
    ),
)
```

The CLI exposes the same trusted limits. A budget denial is recorded like any
other denial and stops the batch before later plan items are evaluated:

```bash
aa run examples/demo.json \
  --allowed-domain example.com \
  --max-actions 10 \
  --max-total-wait-ms 30000
```

Budgets are local to one `execute_many()` or CLI invocation. They bound batch
items reaching policy evaluation and cumulative *requested* `wait` milliseconds
before calls to `Executor.execute`; a custom executor may still retry or do
work internally. Budgets do not add cross-process quotas, network bandwidth
controls, retries, idempotency, transaction rollback, or an input-size/memory
limit: the CLI parses its complete JSON plan before the runtime applies a
budget. To leave trace evidence, an API batch at its action cap may read one
additional candidate, but that candidate never reaches policy, confirmation, or
an executor. Bound or materialize side-effecting generators upstream.

For compatibility, an unbudgeted batch still dispatches through an embedding
subclass's execution hooks. A budgeted batch fails closed before consuming input
when legacy `execute()` or `_execute()` hooks are overridden, because silently
bypassing an application's approval or audit logic would be unsafe. Use
policy/executor composition for budgeted batches, or keep the legacy override
unbudgeted.

## Safety defaults

- Actions run through deterministic policies before reaching an executor.
- The standard policy asks for confirmation before `click` and `type`
  proposals, and for higher declared risks. A confirmation handler must return
  the literal built-in `True` to approve; every other result fails closed. It
  cannot prove an action's business intent is safe.
- The unoverridden base `ActionRuntime` execution pipeline accepts only exact
  `Action` instances and rebuilds an immutable, canonical snapshot before
  hooks run. Normalize application or provider input with `Action(...)` or
  `Action.from_dict(...)` rather than passing duck-typed objects or subclasses.
  An integration that directly overrides `execute()` owns and must enforce its
  own admission and confirmation boundary; budgeted batches reject execution
  hook overrides rather than silently bypassing them.
- Default CLI traces retain only a narrow structural/numeric subset; action IDs,
  strings, metadata, policy text, errors, and artifact paths are redacted.
  `--unsafe-trace` is only for local, non-sensitive test data.
- Replay is deliberately narrower than trace inspection: it only accepts a
  non-empty unredacted current trace run (or a consistently marker-free legacy
  trace) whose events recorded an explicit `allow`/`confirm` decision and a
  completed `dry_run` result. A trace is not a retry queue, so real `success`
  events and denied, cancelled, failed, incomplete, or budget-blocked events
  all fail closed.
- Navigation can be restricted with repeatable `--allowed-domain` options.
  An allowlist is a defense in depth control, not a complete network sandbox.
- Standard navigation and domain allowlists accept only ASCII hostnames. For an
  internationalized domain, configure the browser-targeted Punycode A-label
  explicitly; this avoids treating Python's legacy IDNA mapping as a
  browser-equivalent security decision.
- The CLI defaults to dry-run. It can validate and record a plan without a
  browser, while real execution is opt-in and requires at least one
  `--allowed-domain`.
- Action plans may be a bare list or an object with an `actions` list. The
  object envelope may carry application-owned metadata, but those fields never
  configure policy or execution authority in the CLI.
- The real Playwright executor permits only `GET` network requests by default.
  Programmatic users must explicitly allow every additional HTTP method; this
  constrains browser egress but does not prove that a `GET` has no business
  side effect.

For a reviewed workflow that genuinely needs a write request, configure only
the methods it needs in application code; the CLI deliberately keeps its
default `GET`-only boundary:

```python
from actionanything.executors import PlaywrightExecutor

executor = PlaywrightExecutor(
    allowed_domains=["example.com"],
    allowed_request_methods={"GET", "POST"},
)
```

The configurable set is `GET`, `HEAD`, `OPTIONS`, `POST`, `PUT`, `PATCH`, and
`DELETE`; `CONNECT` and `TRACE` are always rejected. A cross-origin request may
also need an explicit `OPTIONS` grant for its browser preflight. Treat every
such grant as trusted application configuration, not action-plan data.
- Plans cannot set their own execution limits. Configure action-count and
  cumulative-wait budgets in trusted application code or CLI arguments.

## Architecture and contributing

- Read the [architecture overview](docs/architecture.md) to add adapters,
  policies, or executors.
- See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.
- Maintainers use the lightweight [AHE maintenance loop](AGENTS.md) to make
  small, evidence-backed improvements to this repository; it is not an
  additional product feature.
- Report vulnerabilities using the private process in [SECURITY.md](SECURITY.md).
- Follow planned work or propose a use case through GitHub Issues.

## Status

ActionAnything is an early-stage open-source project. APIs may change before
version 1.0. Use real browser execution only in isolated test environments.
Policies and trace redaction are useful controls, not substitutes for a
dedicated browser profile, host/network isolation, least-privilege accounts,
or application-level approval.

## Why ActionAnything?

Computer-use models can propose clicks, typing, navigation, and other actions,
but production applications still need deterministic safety controls around
those proposals. ActionAnything keeps those controls outside the model; it does
not call a model or decide the application's business policy for it.

## License

[MIT](LICENSE)
