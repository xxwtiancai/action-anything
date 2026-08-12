# ActionAnything

> Let any AI safely act on anything.

ActionAnything is a model-agnostic runtime for executing, approving, recording,
and replaying AI agent actions. It provides a small, auditable layer between a
model's proposed action and the browser or desktop environment that executes it.

## What works today

- A model-agnostic schema for navigation, click, type, scroll, wait, and screenshot actions.
- A composable policy engine with risk gates, domain allowlists, and sensitive-target checks.
- Human confirmation before consequential actions.
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
from actionanything import Action, ActionKind, ActionRuntime, DryRunExecutor

runtime = ActionRuntime(DryRunExecutor())
result = runtime.execute(
    Action(ActionKind.NAVIGATE, {"url": "https://example.com"})
)
print(result.to_dict())
```

## Safety defaults

- Actions run through deterministic policies before reaching an executor.
- External and critical actions require confirmation by default.
- CLI traces redact text, values, secrets, passwords, and tokens by default.
- Navigation can be restricted with repeatable `--allowed-domain` options.
- Real browser execution is always opt-in.

## Architecture and contributing

- Read the [architecture overview](docs/architecture.md) to add adapters,
  policies, or executors.
- See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.
- Report vulnerabilities using the private process in [SECURITY.md](SECURITY.md).
- Follow planned work or propose a use case through GitHub Issues.

## Status

ActionAnything is an early-stage open-source project. APIs may change before
version 1.0. Use real browser execution only in isolated test environments.

## Why ActionAnything?

Computer-use models can propose clicks, typing, navigation, and other actions,
but production applications still need deterministic safety controls around
those proposals. ActionAnything keeps that control outside the model.

## License

[MIT](LICENSE)
