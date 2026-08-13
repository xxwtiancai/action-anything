# Iteration 015: Bounded executor result output

**Status: implementation, local validation, staged-format verification, and
independent review complete; remote CI pending.**
This is an Agentic Harness Engineering (AHE) maintenance record for
ActionAnything; it does not add an Agent Harness product feature.

## Observation

Iteration 014 bounded and cycle-checked `Action.metadata`, but
`ActionResult.output` still used unbounded recursive normalization. A direct
API caller could therefore construct a cyclic result and receive
`RecursionError`. The base runtime happened to turn a custom executor's cyclic
output into a generic executor failure, but that outcome depended on the
exception path rather than an explicit public result contract.

## Hypothesis

If canonically constructed `ActionResult.output` uses the existing
raw-identity-aware normalizer with a 64-container boundary, direct result
construction will reject direct and indirect cycles deterministically; a base
runtime will continue to fail closed and record a safe generic error when a
custom executor returns invalid output.

The hypothesis is falsified if a 64-container output is rejected, a 65th is
accepted, a cycle reaches a trace, or invalid executor output is reported as a
successful action.

## Scope

- Apply the existing 64-container raw-identity cycle contract to the required
  root `ActionResult.output` mapping, counting every mapping/list/tuple
  container including the root.
- Add direct API regressions for depth, direct/indirect cycles, and shared
  children.
- Add a base-runtime + unredacted trace regression for a cyclic custom
  executor result.
- Document the structural boundary and its limits.

This does not change action schemas, confirmation, executor permissions, CLI
input, trace replay input, output byte/key/string limits, or custom executor
resource controls.

## Actual validation

Using the repository's bundled Python 3.12 runtime:

- `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/actionanything-output-pycache python3 -m unittest tests.test_actions tests.test_runtime tests.test_recorder -q` — 65 passed.
- `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/actionanything-output-pycache python3 -m unittest discover -s tests -q` — 122 passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/actionanything-output-compile python3 -m compileall -q src` — passed.
- `git diff --check` — passed.
- `git diff --cached --check` — passed after selectively staging the eight
  files in this iteration.
- Independent read-only review found no P0. It independently ran the 65
  action/runtime/recorder tests, confirmed the base-runtime behavior, and
  required the documentation to distinguish it from direct `TraceRecorder`
  use.

## Residual risks and next question

The 64-container contract prevents unbounded recursive shape processing but is
not a size, width, string-length, or CPU limit. Custom executors remain
application-owned and can have independent side effects or resource costs.
`TraceRecorder.record()` does not independently re-admit a result object;
direct recorder integrations must provide their own canonical-result boundary.

The next question is whether ActionAnything needs a separate, trusted
application-level output-size policy without turning result handling into a
general sandbox.
