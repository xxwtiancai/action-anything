# Iteration 011: Trace input normalization

**Status: validated locally, independently reviewed, and remote CI passed.**
This is an Agentic Harness Engineering (AHE) maintenance record. It captures a
small, evidence-backed maintenance loop for ActionAnything; it does not add a
runtime Agent Harness.

## Observation

Trace inspection and replay accept JSONL from outside the current process.
Before this iteration, a deeply nested decoded event could cause recursive
redaction scanning to raise `RecursionError`; malformed `result` structures
could pass trace reading and later make `aa inspect` call `.get()` on a list.
Some Python decoder recursion failures also escaped the trace-input error path.

## Hypothesis

If decoded trace events have a deterministic structural-depth cap, redaction
scanning is iterative, and `action`/optional `result` objects are validated at
the reader boundary, `aa inspect` and `aa replay` will reject malformed input
with stable errors before any replay execution is constructed.

The hypothesis is falsified if a deep/malformed trace causes an unhandled
recursion or attribute exception, or if normal trace inspection/replay stops
working.

## Scope

- Cap trace-event nesting at 128 mapping/list/tuple layers for both writing and
  reading. This leaves room for the trace envelope around canonical metadata.
- Make redaction discovery iterative and cycle-tolerant for public helper use.
- Normalize decoder recursion failures and reject non-mapping `result` fields
  with a line-numbered `ValueError`.
- Cover direct reader, `aa inspect`, `aa replay`, default redaction, and normal
  trace behavior with deterministic offline tests.
- Do not change trace writer atomicity, replay authority/admission policy,
  action-plan limits, or general JSON resource quotas.

## Actual local validation

Using a supported Python 3.12 interpreter with `PYTHONPATH=src` and a temporary
bytecode-cache directory:

```bash
python -m unittest tests.test_recorder tests.test_cli -v
python -m unittest discover -s tests -v
python -m compileall -q src
git diff --check
git diff --cached --check
```

The targeted tests exercise a 1,000-level redaction scan, a 2,000-level JSONL
event, invalid `result: []`, a cycle-safe public redaction helper, rejected
overdeep unsafe-trace writing, normal `inspect`, successful shallow unsafe-trace
replay, and redacted-trace rejection. Results: **15 targeted tests passed** and
**72 offline tests passed**. Source compilation and the working-tree format
check passed; the staged format check is performed before commit.

## Independent review

Review initially identified a writer/reader contract mismatch: a legal deep
unsafe trace could be written and then rejected by the reader. The writer and
reader now share the 128-container trace-event boundary, and the writer checks
before opening a file. Boundary verification confirmed metadata nesting through
125 layers can write/read while 126 layers are rejected before file creation.
The review found no remaining P0/P1 issues.

Remote CI passed on Python 3.10, 3.11, 3.12, and 3.13, plus distribution build,
CodeQL, and dependency review.

## Residual risks

The reader still consumes a complete JSONL line before applying its structural
cap, so line byte size and decoder CPU/memory are not bounded here. This change
does not make traces trustworthy, replayable by default, secret-free, or safe
to publish. Concurrent writer behavior and replay admission are separate
maintenance concerns.
