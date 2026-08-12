# Iteration 004: Versioned schema export

## Observation

ActionAnything had a strict Python `Action` intake boundary but no portable,
machine-readable contract for an application configuring structured model
output, generating a plan form, or checking plan shape before invoking the
runtime. The architecture roadmap identified JSON Schema export as a missing
interoperability capability.

## Falsifiable hypothesis

If the project exports small, self-contained Draft 2020-12 schemas that mirror
the accepted action and plan shapes, consumers can validate common malformed
payloads before runtime without widening action authority. The hypothesis is
supported only if the documents pass a standard meta-schema check, accept every
built-in canonical action kind, reject representative invalid shapes, and the
CLI exports the same documents as the public Python API.

## Small change and boundary

- Added `action_schema()` and `action_plan_schema()` in `schemas.py`, each with
  a stable v1 URN and only local `$ref` values.
- Added `aa schema action` and `aa schema plan` for deterministic JSON output.
- Added a development-only `jsonschema` dependency for contract tests; the
  runtime package remains dependency-free.

The schemas are an input/interoperability aid, not the product's authorization
boundary. Canonical Python validation, minimum-risk normalization, policy,
confirmation, and executor containment still decide whether an action reaches
an executor.

## Verification

Ran with Python 3.12 and a temporary development environment:

```bash
python -m unittest discover -s tests -v
```

Result: **77 tests passed**, including Draft 2020-12 meta-schema checks, all
six canonical action kinds, representative schema rejection cases, plan
envelope behavior, and CLI/API equivalence.

### Review follow-up

An independent PR review found that repeated selector and coordinate schemas
shared mutable dict instances *within one exported document*. A caller who
customized one nested value in memory could therefore alter another definition
unexpectedly. The export now creates a fresh dict at every insertion site, and
a regression test mutates `clickParams` then proves the corresponding
`typeParams` and `scrollParams` definitions remain unchanged.

After that follow-up, ran with Python 3.12 and the declared development-only
dependency in a temporary directory:

```bash
PYTHONPATH=<temporary-dev-dependencies>:src \
  python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=<temporary-pycache> \
  python -m compileall -q src
git diff --check
```

Result: **78 tests passed**; compilation and whitespace checks passed.

Also built an sdist and wheel, ran `twine check`, installed the wheel into a
fresh temporary environment, then verified `aa schema action`, `aa schema
plan`, JSON parsing, and `aa validate examples/demo.json`. All checks passed.
The workspace's tracked `egg-info` permissions prevented an in-place package
build, so the package check used an isolated source copy of the same diff. The
package build emitted pre-existing setuptools deprecation warnings about the
project's license metadata; this iteration did not change licensing.

## Residual risk and next question

JSON Schema cannot fully express URL parsing, safe filesystem semantics,
finite non-JSON values, Python's distinction between an integer token and a
JSON number such as `1.0`, runtime risk floors, or browser/domain policy. The
next interoperability question is whether to add a similarly versioned policy
outcome schema without exposing policy text or weakening trace redaction. A
future trusted execution-budget feature should explicitly define whether its
name is reserved in the open plan envelope rather than silently assigning
authority to model-provided JSON.
