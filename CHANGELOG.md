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
- Browser containment, trace-redaction, CodeQL/dependency-review, release, and
  community-health foundations, plus AHE iteration records for maintainers.
- `ExecutionBudget` and matching CLI flags for trusted per-batch action-count
  and cumulative-wait limits.
- A bounded, cycle-checked `Action.metadata` intake boundary and short,
  non-reflective diagnostics for malformed action-plan fields and values.

### Changed

- The standard policy now requires an explicit domain allowlist for all
  navigation, including dry-run, and confirms `click`/`type` at the reversible
  risk floor.
- Default traces now retain only narrow structural/numeric fields. Use
  `--unsafe-trace` only for local, non-sensitive test data.
- Confirmation now accepts only the literal built-in `True`; other truthy
  handler results fail closed as `cancelled`.
- `PolicyEngine` gives each policy an isolated canonical action snapshot;
  custom policies must return `PolicyOutcome` values rather than use action
  mutation to communicate with later policies.
- `Action` and `ActionResult` normalize accepted scalar subclasses to their
  built-in JSON values before validation and storage, so custom `__str__`,
  `__int__`, or `__float__` behavior cannot change a policy or executor view
  after intake.
- `Action.metadata` accepts at most 64 nested mapping/list/tuple containers
  and rejects circular references before an action reaches policy or execution.

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
  and default trace JSONL intentionally cannot be replayed; use an explicit,
  local `--unsafe-trace` test trace for replay.
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
- Accepted string, integer, and float subclasses are now stored as exact
  built-in JSON values. Mapping keys are normalized as built-in strings and
  reject aliases that collide after normalization. Integrations that depended
  on custom scalar conversion, comparison, hashing, or serialization behavior
  must pass ordinary JSON-compatible values instead.
