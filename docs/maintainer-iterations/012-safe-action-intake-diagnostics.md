# Iteration 012: Safe action-intake diagnostics

**Status: local validation complete; independent review and remote CI pending.**
This is an Agentic Harness Engineering (AHE) maintenance record. It describes
a small, falsifiable ActionAnything improvement; it does not add an Agent
Harness to the product.

## Observation

Canonical action validation previously copied unsupported top-level field
names, parameter names, `kind`/`risk` values, and result statuses into error
messages. The CLI includes those messages in stderr. An untrusted plan could
therefore make a terminal, CI log, or collected application log contain an
arbitrarily long marker or a misplaced secret.

## Hypothesis

If action-intake failures use stable structural categories instead of
untrusted text, API exceptions and `aa validate` stderr will remain concise
and will not contain an unsupported field name or enum value. Valid action
normalization must remain unchanged.

The hypothesis is falsified if a long sentinel appears in an
`ActionValidationError`, `ActionResult` validation error, or CLI stderr; or
if normal action and CLI validation regress.

## Scope

- Replace reflected messages for unknown action-plan fields, unknown action
  parameters, unsupported action kind/risk, and unsupported result status.
- Avoid sorting or joining unknown field-name sets solely to construct an
  error message.
- Cover direct action/result construction and `aa validate` with a long
  untrusted sentinel.
- Do not alter action semantics, confirmation, policy, executor behavior,
  trace redaction, nested metadata/output diagnostics, or CLI input quotas.

Nested metadata/output validation is deliberately left to its owning bounded
metadata and trace-input iterations. Keeping this change at the outer action
intake avoids creating an overlapping rewrite of those active changes.

## Actual local validation

Using a supported Python 3.12 interpreter with `PYTHONPATH=src` and a
temporary bytecode-cache directory:

```bash
python -m unittest tests.test_actions tests.test_cli -v
git diff --check
```

Results: **18 targeted tests passed** and the working-tree format check
passed. The new regressions use a 4,096-character sentinel and verify it is
absent from direct validation errors and CLI stderr, while the CLI still names
the action index and stable rejection category.

## Residual risks and next question

This iteration does not make application logs, custom exception handlers,
untrusted `ActionResult.output`, metadata paths, or trace artifacts safe to
share. Callers must still avoid placing secrets in plans and must handle their
own logs safely.

The next higher-priority runtime iteration is to require a confirmation
handler to return the literal built-in `True`, and to reject non-canonical
duck-typed action objects before policy or executor code runs. It must be
stacked after the pending execution-budget integration because both change the
runtime batch entry point.
