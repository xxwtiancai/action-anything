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

### Changed

- The standard policy now requires an explicit domain allowlist for all
  navigation, including dry-run, and confirms `click`/`type` at the reversible
  risk floor.
- Default traces now retain only narrow structural/numeric fields. Use
  `--unsafe-trace` only for local, non-sensitive test data.
- Action-intake diagnostics no longer reflect unsupported action field names,
  parameter names, enum values, or result statuses supplied by untrusted data.

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
