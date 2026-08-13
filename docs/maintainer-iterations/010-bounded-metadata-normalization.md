# Iteration 010: Bounded metadata normalization

**Status: validated locally, independently reviewed, and remote CI passed.**
This is an Agentic Harness Engineering (AHE) maintenance record. It records a
small, falsifiable ActionAnything input-boundary improvement; it does not add
an Agent Harness to the product.

## Observation

`Action.metadata` accepts arbitrary JSON-compatible nesting and is recursively
frozen before policy or executor code sees it. A deeply nested JSON plan, or a
cyclic Python mapping provided by an embedding application, could therefore
raise `RecursionError` instead of the public `ActionValidationError` contract.
The CLI only converts expected validation failures into its normal usage error.

## Hypothesis

If metadata freezing enforces a small, deterministic container-depth limit and
rejects ancestor cycles, malformed input will fail at the canonical intake
boundary with `ActionValidationError` rather than escaping as a recursion
failure. Shallow metadata, immutable copies, and action parameters should
retain their existing behavior.

The hypothesis is falsified if a metadata tree beyond the limit or with a
cycle raises `RecursionError`, or if a normal shallow metadata payload stops
round-tripping.

## Scope

- Limit `Action.metadata` to 64 nested mappings/lists/tuples.
- Reject only references on the active ancestor path, so shared non-cyclic
  substructures remain valid.
- Cover direct construction, `Action.from_dict`, and CLI plan validation.
- Normalize a JSON decoder recursion failure at the CLI plan boundary.
- Do not impose a JSON byte-size/key-count quota, alter action parameters,
  add dependencies, or change runtime/executor behavior.

## Actual local validation

Using a supported Python 3.12 interpreter with `PYTHONPATH=src` and a temporary
bytecode-cache directory:

```bash
python -m unittest tests.test_actions tests.test_cli -v
python -m unittest discover -s tests -v
python -m compileall -q src
git diff --check
git diff --cached --check
```

Results: **21 targeted tests passed** and **72 offline tests passed**. Source
compilation and the working-tree format check passed; the staged format check
is performed before commit. The targeted suite validates 64 nested containers,
deterministic rejection of a 65th container, direct and mixed container cycles,
permitted shared subtrees, a JSON decoder recursion failure, and the CLI's
normal parameter-error path.

## Independent review

An independent read-only review found no P0/P1 issues. It requested explicit
coverage for a dictionary-to-list-to-dictionary cycle and for shared children
that are not cycles; both are now covered. The review also identified the JSON
decoder as a preceding recursion boundary, so `_load_actions` normalizes its
`RecursionError` into the CLI's stable `ValueError` path.

Remote CI passed on Python 3.10, 3.11, 3.12, and 3.13, plus distribution build,
CodeQL, and dependency review.

## Residual risks

This only bounds recursive metadata normalization. A plan may still be large
in bytes, wide in key count, expensive for the JSON decoder, or contain values
that an embedding application should reject under its own quota/policy.
`ActionResult.output` and trace loading have separate recursive input paths
and are deliberately not changed by this iteration. A Python caller with
arbitrary in-process authority remains outside the untrusted JSON boundary.
