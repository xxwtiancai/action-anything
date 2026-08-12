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
- Provider adapters that normalize supported provider output without making model calls.
- A composable policy engine with risk gates, domain allowlists, and sensitive-target checks.
- Trusted per-batch execution budgets for action count and cumulative wait time.
- Human confirmation for actions that the configured policy gates.
- A zero-dependency dry-run executor and an optional Playwright browser executor.
- Redacted JSONL traces plus trace inspection and replay for local test data.
- A small `aa` CLI for running portable JSON action plans.

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
- The CLI defaults to dry-run. It can validate and record a plan without a
  browser, while real execution is opt-in and requires at least one
  `--allowed-domain`.
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
