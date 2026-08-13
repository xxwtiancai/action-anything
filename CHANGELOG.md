# Changelog

All notable changes to ActionAnything are documented in this file. The project
uses [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial public alpha release process and project foundations.
- Strict canonical validation for built-in action plans, an `aa validate`
  command, and an OpenAI Responses `computer_call` normalizer that rejects
  unsupported calls and pending provider safety checks.
- A strict Anthropic Computer Use `tool_use` adapter for direct, version-bound
  coordinate clicks, focused typing, bounded waits, and screenshots. It
  rejects unsupported or ambiguous provider actions rather than approximating
  them.
- Browser containment, trace-redaction, CodeQL/dependency-review, release, and
  community-health foundations, plus AHE iteration records for maintainers.
- Self-contained, versioned Draft 2020-12 schemas for action and action-plan
  inputs, available through `action_schema()`, `action_plan_schema()`, and
  `aa schema action|plan`.
- Optional exact `SelectorAllowlistPolicy` for least-privilege `click` and
  `type` target admission, while retaining confirmation on selector matches.
- `ExecutionBudget` and matching CLI flags for trusted per-batch action-count
  and cumulative-wait limits.

### Changed

- `PlaywrightExecutor` now permits only `GET` browser requests by default.
  Applications enabling real execution must explicitly configure every
  additional HTTP method they require.
- Domain allowlists and standard navigation now reject Unicode hostnames.
  Internationalized domains must be configured as explicit ASCII Punycode
  A-labels so policy comparison is not widened by a legacy IDNA conversion.
- Trace inspection and replay now reject excessively nested or malformed trace
  events with stable input errors rather than allowing recursive scans or
  event-shape assumptions to fail unexpectedly.
- Action metadata now has a 64-container nesting limit and rejects circular
  Python container references with a stable validation error. This bounds
  recursive normalization; it is not a general JSON size or key-count quota.
- The standard policy now requires an explicit domain allowlist for all
  navigation, including dry-run, and confirms `click`/`type` at the reversible
  risk floor.
- Default traces now retain only narrow structural/numeric fields. Use
  `--unsafe-trace` only for local, non-sensitive test data.
- Trace recording now retries positive short writes and reports zero-progress
  writes as an audit failure instead of silently accepting a truncated JSONL
  event. Cooperating local trace writers serialize an event write and possible
  rollback so one recorder does not truncate another recorder's event.
- Confirmation now accepts only the literal built-in `True`; other truthy
  handler results fail closed as `cancelled`.
- `PolicyEngine` gives each policy an isolated canonical action snapshot;
  custom policies must return `PolicyOutcome` values rather than use action
  mutation to communicate with later policies.

### Breaking changes

- Built-in action plans reject unknown parameters and invalid/missing required
  fields. `click` requires one selector or an `x`/`y` pair; `type` uses
  `selector` or focused-input mode; `scroll` and `wait` require bounded
  parameters; screenshot paths must be safe relative `.png` names.
- Existing applications without a confirmation handler will now receive
  `cancelled` for standard-policy `click` and `type` actions. Supply an
  application-owned confirmation handler or an explicitly reviewed custom
  policy.
- `PlaywrightExecutor` now requires a non-empty `allowed_domains` allowlist,
  defaults to `GET` browser requests, and default trace JSONL intentionally
  cannot be replayed; use an explicit, local `--unsafe-trace` test trace for
  replay. Applications needing `HEAD`, `OPTIONS`, or write-capable methods
  must set `allowed_request_methods` explicitly.
- Existing applications that configure Unicode domain names must migrate to
  their intended ASCII Punycode A-labels.
- Trace replay now fails closed unless every event is a complete unredacted
  dry-run with explicit allow/confirm evidence; it must not turn a real prior
  execution, failure, cancellation, denial, or budget block into a later
  execution attempt.
- A budgeted `execute_many()` now fails closed if an embedding subclass
  overrides `execute()` or `_execute()`. Unbudgeted batches retain legacy
  dispatch; compose custom policy or executor behavior for a budgeted batch.
- The unoverridden base `ActionRuntime.execute()` and `execute_many()` accept
  only exact `Action` objects and rebuild a canonical immutable snapshot.
  Normalize integration input with `Action(...)` or `Action.from_dict(...)`;
  duck-typed values and `Action` subclasses are now rejected before policy,
  confirmation, recording, or execution. A direct `execute()` override remains
  application-owned and must enforce its own boundary.
