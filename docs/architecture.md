# Architecture

ActionAnything separates provider-shaped model output from deterministic action
execution. The embedding application makes any model calls; an adapter only
normalizes a supported provider response into an `Action`. The runtime then
decides whether that action is allowed to reach an executor. ActionAnything
does not own model credentials, prompts, provider safety acknowledgements, or
the application's business policy.

```mermaid
flowchart LR
    APP[Embedding application<br/>owns model calls and credentials] --> M[Provider output]
    M --> N[Adapter normalizer<br/>no provider I/O]
    N --> A[Action schema]
    A --> P[Policy engine]
    P -->|allow| E[Executor]
    P -->|confirm| H[Human approval]
    H -->|approved| E
    P -->|deny| R[ActionResult]
    H -->|rejected| R
    E --> R
    A --> T[Trace recorder]
    P --> T
    R --> T
```

## Design principles

### Model agnostic

Providers are represented by adapters that normalize documented, supported
output into the action schema. An adapter is not a model client: it must not
make provider requests, own API keys, send screenshots back to a model, or
approve a provider safety check. The policy and executor layers must not depend
on a provider SDK. The application decides if, when, and how provider calls are
made.

### Safe by construction

Safety checks live in regular Python code, not only in a prompt. A model can
request an action, but it cannot override a deny decision or approve itself.
These checks do not establish the semantic safety of a page, model request, or
business operation; applications still need their own policy and human review
for consequential work.

### Dry-run first

The CLI uses `DryRunExecutor` unless a user explicitly passes `--execute`.
This makes plans inspectable before they touch a browser. Dry-run does not
bypass policy: navigation still needs an explicit allowlist, and the real
Playwright executor additionally requires one before it can start.

### Local evidence, not a security boundary

Every evaluated action can be written to JSONL. Default events retain only a
small structural/numeric subset; arbitrary strings, identifiers, metadata,
policy text, errors, and artifact paths are redacted unless the user explicitly
opts into an unsafe local test trace. JSONL append behavior does not make traces
tamper-proof, safe to publish, or a substitute for secret management.

### Versioned interchange contracts

`action_schema()` and `action_plan_schema()` export self-contained JSON Schema
Draft 2020-12 documents with stable v1 URN identifiers. They are intended for
structured model output, form generators, and offline interoperability; they
are emitted locally and do not fetch remote schema references. Each public call
returns a new JSON-compatible mapping so an embedding application can annotate
or transform it without changing future exports.

These contracts intentionally describe only structural input shape. Canonical
`Action` validation remains authoritative for URL and filesystem semantics,
finite values, Python's integer-token distinction (for example `1` versus
`1.0`), and minimum-risk normalization. Policy, confirmation, domain
allowlisting, and executor controls remain separate runtime boundaries.

## Core modules

| Module | Responsibility |
|---|---|
| `actions.py` | Stable action, risk, and result schemas |
| `schemas.py` | Versioned JSON Schema exports for action and action-plan inputs |
| `adapters/` | Provider-output normalizers; no model calls or credentials |
| `policy.py` | Composable allow, confirm, and deny decisions |
| `executors.py` | Dry-run and optional Playwright execution |
| `runtime.py` | Policy-to-confirmation-to-execution orchestration |
| `recorder.py` | Redacted JSONL traces and trace loading |
| `cli.py` | Portable plans, trace inspection, and replay |

## Extending the project

### Add a model adapter

Translate a provider response into `Action.from_dict(...)`. Keep authentication,
streaming, retries, model requests, safety acknowledgement, and provider
session state in the embedding application rather than the adapter. Store only
useful, non-sensitive provenance under `Action.metadata`; reject unsupported
provider fields instead of silently approximating them.

The built-in `AnthropicComputerUseAdapter` illustrates the boundary: the
embedding application pins `computer_20250124` or `computer_20251124` plus the
display dimensions used in its request, then passes one direct `tool_use`
block to the adapter. A returned block does not establish which computer-tool
definition or screenshot coordinate space produced it. The adapter supports
only coordinate clicks, focused typing, bounded waits, and screenshots; it
rejects provider scroll, key, drag, multi-click, zoom, and programmatic-caller
semantics instead of inventing a translation. It still does not make a model
call, send a screenshot, acknowledge a provider safeguard, or approve local
execution.

### Add an executor

Implement `Executor.execute(action)` and expose `is_dry_run`. Executors should
reject unsupported actions, avoid hidden retries, and return JSON-compatible
metadata rather than provider objects.

The optional `PlaywrightExecutor` also treats its domain and request-method
configuration as trusted application input. It allows only `GET` requests by
default; `HEAD`, `OPTIONS`, and write-capable HTTP methods require an explicit
`allowed_request_methods` grant. This constrains browser egress, but cannot
prove a server treats any method as business-safe.

The CLI intentionally does not accept a request-method flag, so its real
executor keeps the `GET`-only default. Applications that need an explicit
method grant construct `PlaywrightExecutor` themselves and retain ownership of
that trusted configuration.

### Add a policy

Implement `Policy.evaluate(action)`. Return `None` when the policy does not
apply. `PolicyEngine` gives deny decisions precedence over confirmation, and
confirmation precedence over allow.

`SelectorAllowlistPolicy` is an opt-in example of target-scoped least
privilege. It only handles `click` and `type`, compares a trusted locator
configuration byte-for-byte, denies coordinate/focused targets that have no
selector, and returns `confirm` even on a match. It is not a CSS parser, glob,
regular-expression matcher, page-state verifier, or replacement for the
browser executor's domain containment.

## Near-term roadmap

- Additional adapters and independently reviewed provider action mappings.
- JSON Schema export for actions and policy outcomes.
- Screenshot evidence associated with each trace step.
- Sandboxed remote executors and explicit resource limits.
- BrowserGym/WebArena-compatible evaluation runners.
- Signed policy bundles for shared deployments.
