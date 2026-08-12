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

## Safety defaults

- Actions run through deterministic policies before reaching an executor.
- The standard policy asks for confirmation before `click` and `type`
  proposals, and for higher declared risks; it cannot prove an action's
  business intent is safe.
- Default CLI traces retain only a narrow structural/numeric subset; action IDs,
  strings, metadata, policy text, errors, and artifact paths are redacted.
  `--unsafe-trace` is only for local, non-sensitive test data.
- Navigation can be restricted with repeatable `--allowed-domain` options.
  An allowlist is a defense in depth control, not a complete network sandbox.
- Standard navigation and domain allowlists accept only ASCII hostnames. For an
  internationalized domain, configure the browser-targeted Punycode A-label
  explicitly; this avoids treating Python's legacy IDNA mapping as a
  browser-equivalent security decision.
- The CLI defaults to dry-run. It can validate and record a plan without a
  browser, while real execution is opt-in and requires at least one
  `--allowed-domain`.

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
