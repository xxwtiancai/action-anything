# 006 · Fail-closed trace replay admission

**Status:** local verification and independent review complete; pending remote
CI.

## Observation

An unredacted JSONL trace is useful local evidence, but a trace event can also
record a denial, cancelled confirmation, executor failure, malformed data, or
an execution-budget stop. Treating every recorded action as a future replay
candidate would silently turn past decisions and uncertain partial failures
into retries.

## Falsifiable hypothesis

If replay admits only one complete trace whose events have explicit `allow` or
`confirm` policy decisions and completed `dry_run` results, any event that was
not safely completed without real effects will reject the entire replay before
a new runtime or executor is created.

## Small scope

- Added one strict replay-admission check before an action is reconstructed.
- Rejected missing/unknown policy or result values, real executor successes,
  policy denials, cancelled confirmations, executor errors, and
  `ExecutionBudget` events.
- Required complete policy/result evidence and one consistent trace-run
  identity profile. Current trace IDs and sequences must agree and increase;
  consistently marker-free legacy traces remain supported.
- Rejected empty trace files before runtime construction. Legacy marker-free
  traces retain compatibility but cannot prove their events came from one
  physical recording session.
- Kept the existing complete-trace preflight: no action is replayed until every
  event has passed admission, redaction, run-identity, and action validation.

No trace signature, idempotency key, state comparison, model call, provider
I/O, retry queue, or executor behavior was added.

## Verification

Run from the repository root with a supported Python environment:

```bash
PYTHONPATH=src python -m unittest tests.test_cli -v
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src
git diff --check
```

Actual local result with Python 3.12: 17 CLI tests and 88 full offline tests
passed; compilation and `git diff --check` passed. The test matrix covers
policy denial, cancelled confirmation, executor error, real executor success,
unknown result status, complete evidence, legacy/current trace identity
profiles, a valid first event followed by an invalid event, and the existing
budget-blocked/replay-redaction paths. The no-runtime assertion is the
completion signal for each rejected trace.

## Residual risk and next question

An admitted replay still re-evaluates current local policy and confirmation,
but it cannot prove the external page, account, or business state is unchanged
since recording. It remains suitable only for local, non-sensitive test data;
production retry and idempotency require application-owned state and controls.

The next independent policy question is whether applications should be able to
configure exact selector allowlists for click/type actions inside an otherwise
allowed domain, without turning selector text into a claim of business safety.
