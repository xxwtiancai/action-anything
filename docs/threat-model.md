# Threat model

ActionAnything is an early-stage runtime that places deterministic checks
between an action proposed by a model or application and an executor that may
touch a browser or desktop environment. This document describes the security
boundary of the project; it is not a claim that the project makes a browser,
model, website, or deployment safe by itself.

## How to read this document

Controls are marked as **implemented**, **in progress**, or **planned**. Only
implemented controls are current security guarantees. In-progress and planned
items are design direction, not a reason to relax deployment safeguards.

The model is reviewed whenever a new action kind, executor, provider adapter,
or trace format changes the project's trust boundary.

## Scope and system boundary

```text
untrusted plan / model output
             |
             v
      ActionAnything intake
             |
             v
      policy + confirmation
             |
             v
   executor (dry-run or browser)
             |
             v
website, local artifacts, and traces
```

The application embedding ActionAnything owns its model selection, prompts,
credentials, policy configuration, confirmation UI, browser profile, and
deployment sandbox. ActionAnything does not take ownership of those systems.
An adapter is only a provider-payload normalizer: it does not make model calls,
store provider credentials, or acknowledge provider safety checks on the
application's behalf.

## Assets to protect

- The operator's authority to navigate, click, type, or otherwise affect an
  external system.
- Credentials, personal information, confidential text, and browser-session
  data available to the executor.
- The integrity of action policies, confirmation decisions, and action traces.
- Local files written as traces or browser artifacts.
- Availability of the host, browser, and services accessed by an action plan.

## Trust boundaries

| Boundary | Why it matters | Current posture |
| --- | --- | --- |
| Model or application to action input | Model output can be malformed, over-broad, or adversarial. | **Implemented in the current code path:** canonical per-action parameter validation, a bounded/cycle-rejecting action-metadata normalizer, minimum risk floors, and per-action policy evaluation. Exported JSON Schemas can assist structured generation and offline shape checks, but are not an authorization or security control. The metadata bound is not a general plan-size or key-count quota, and structural validity does not establish safe semantic intent. |
| Action input to policy | A model must not be the only authority deciding whether an action is safe. | **Implemented in the unoverridden base runtime pipeline:** exact `Action` admission plus canonical snapshot reconstruction; deny-over-confirm-over-allow policy precedence; explicit ASCII/Punycode domain allowlists for navigation; confirmation for the reversible-risk floor used by `click` and `type` proposals, as well as higher declared risks. Unicode host names are rejected rather than silently converted with a potentially browser-incompatible IDNA mapping. Applications can opt into an exact selector allowlist that denies coordinate/focused click/type targets and still requires confirmation for a selector match. A direct application `execute()` override owns its own boundary. |
| Policy to executor | A policy decision should happen before an executor acts. | **Implemented:** the base `ActionRuntime` evaluates policy before calling its executor, and each installed policy receives an isolated canonical action snapshot; a confirmation handler must return the literal built-in `True`, while missing, exceptional, or merely truthy results cancel. |
| Executor to browser or desktop | Browser content, redirects, downloads, and site behavior are untrusted. | **Implemented in the current code path:** real Playwright execution is opt-in; its configured allowlist is checked for requests and current-page URLs; only `GET` requests are permitted by default, while additional methods need trusted executor configuration; downloads, Service Workers, routed WebSockets, and popups are conservatively blocked. Method restriction does not make a server-side operation read-only. This is defense in depth, not a complete browser, host, or network sandbox. |
| Runtime to trace/artifact storage | Logs can reproduce sensitive data even when action input is redacted. | **Implemented in the current code path:** default traces retain only a narrow structural/numeric subset, redact action IDs, strings, metadata, policy text, error text and artifact identifiers, reject unsafe existing trace files, and fail closed on malformed or excessively nested trace events during inspection/replay; Playwright screenshot paths are constrained. This is not secret management or a guarantee that arbitrary browser artifacts are safe to share. |
| Provider adapter to runtime | Provider-specific payloads can change or carry unsafe semantics. | **Implemented:** the OpenAI computer-use adapter normalizes only a documented subset of completed calls and rejects pending safety checks. The Anthropic adapter accepts a narrow ordinary-direct `tool_use` subset bound by the application to a trusted tool version and display size: omitted or `null` caller values are compatible, while a non-empty caller must be explicit `direct`. Both perform no provider I/O. A missing provider-review field is not local approval: `PolicyEngine` and application confirmation remain authoritative. **Planned:** independently reviewed mappings for additional provider actions and protocol changes. |

## Key threats and mitigations

| Threat | Mitigations and residual risk |
| --- | --- |
| A model proposes an unsafe or malformed action. | The runtime evaluates installed policies before execution and normalizes supported action parameters. Canonical shape and risk floors are not a complete security schema, and neither caller-supplied risk nor a model's framing establishes real-world intent. Keep confirmations enabled and apply application/business policy before real execution. |
| A navigation reaches an unapproved domain. | `DomainAllowlistPolicy` validates explicit `navigate` actions. The current browser executor also attempts to apply its configured allowlist to intercepted requests and current-page URLs. An allowlist is not a full network sandbox: it does not replace DNS, proxy, browser, host, or deployment-level containment. Use isolated test environments and explicit domain allowlists. |
| A click or type reaches an unintended control on an allowed page. | `SelectorAllowlistPolicy` can restrict `click` and `type` proposals to exact trusted selector strings, denying coordinate clicks and focused typing. It performs no locator normalization or matching beyond exact text, and a match still requires confirmation. A selector does not prove element uniqueness, dynamic DOM state, business intent, page origin, or post-action navigation; pair it with browser containment and application policy. |
| Prompt injection from web content changes the agent's behavior. | Treat all remote content as untrusted instructions. ActionAnything does not detect or neutralize semantic prompt injection. Use a constrained plan, a human approval step, test accounts, and an isolated browser profile. |
| Sensitive data leaks into a trace, issue, log, or screenshot. | Default trace recording intentionally keeps only action kind/risk, action numeric parameters, policy decision, status, bounded numeric results, timestamp, and sequence; it redacts arbitrary strings, identifiers, metadata, policy text, errors and artifact names. It is not a secret-management system and must not be relied on to sanitize arbitrary browser artifacts or external logs. Do not put secrets in plans or share traces/artifacts without review. |
| A screenshot or artifact write reaches an unintended local path. | The current Playwright screenshot path is constrained under its artifact directory and reserves a fresh output. This does not make every executor or caller-supplied filesystem path safe. Avoid untrusted paths and use a restricted working directory. |
| A browser action affects a real account or external service. | Use least-privilege, disposable credentials; maintain human confirmation for consequential actions; and run in a dedicated browser profile or sandbox. The project does not infer every destructive action from page semantics. |
| A trace replay retries an uncertain or previously rejected action. | Replay is a constrained local reproduction tool, not a job queue. It accepts only a non-empty unredacted current trace run (or consistently marker-free legacy trace) with explicit `allow`/`confirm` policy evidence and completed `dry_run` results; real execution successes, denied, cancelled, failed, malformed, or budget-blocked events reject the entire replay before a runtime is created. The current runtime evaluates policy and confirmation again; this does not prove the external state is unchanged or make an action idempotent. |
| A long or repeated plan exhausts resources or causes repeated side effects. | Applications can set a trusted per-batch `ExecutionBudget` for action-count and cumulative requested `wait` time; the CLI exposes matching flags. It does not provide cross-call quotas, rate limits, transaction rollback, idempotency, browser CPU/memory, network bandwidth, or internal-executor retry guarantees. Applications must impose those broader controls and recovery practices. |
| A dependency or release is compromised. | The core package minimizes runtime dependencies; the optional browser executor depends on Playwright and a browser runtime. Pin and review deployment dependencies, verify release provenance where available, and avoid running unreviewed code with production credentials. |

## Non-goals

ActionAnything does not currently claim to:

- prove that a model's intent is safe or that a click is non-destructive;
- act as a model client, provider credential store, or provider safety-review
  workflow for the embedding application;
- replace sandboxing, operating-system permissions, credential storage, RBAC, or
  network controls;
- protect a reused browser profile from its own cookies, extensions, downloads,
  or site access;
- prevent all data disclosure through model prompts, web pages, screenshots, or
  third-party services; or
- provide multi-tenant isolation, transaction rollback, or a production
  compliance certification.

## Deployment guidance

Before enabling a real executor:

1. Start with dry-run and inspect the normalized plan and trace.
2. Supply explicit domain allowlists for navigation. The CLI requires at least
   one `--allowed-domain` for real execution; use the same explicit boundary in
   programmatic policy configuration and a dedicated, isolated browser profile.
3. Use test accounts or least-privilege credentials with no unnecessary access.
4. Require a human to approve external, irreversible, or ambiguous actions.
5. Keep plans, traces, screenshots, and logs out of public issue trackers and
   restrict local access to them.
6. Set a trusted `ExecutionBudget`, executor timeouts, and application-level monitoring; apply additional session, rate, network, and account limits outside this package.
7. Treat `--unsafe-trace` as unsuitable for personal, confidential, or
   production data.

## Security change requirements

New actions, executors, and provider adapters should document their inputs,
side effects, policy interaction, artifact behavior, and residual risk. Adapter
changes must state how unsupported provider fields and provider safety checks
are rejected, while keeping model I/O in the embedding application. They must
add tests for rejection paths as well as successful execution. A change that
broadens authority, weakens default confirmation, or changes redaction requires
explicit maintainer review.

## Reporting a vulnerability

Follow [SECURITY.md](../SECURITY.md) and use GitHub's private vulnerability
reporting flow. Do not disclose exploit details in a public issue, pull request,
or trace.
