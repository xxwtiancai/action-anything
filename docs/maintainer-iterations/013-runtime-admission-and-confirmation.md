# Iteration 013: Runtime admission and literal confirmation

**Status: local validation and independent review complete; remote CI pending.**
This is an Agentic Harness Engineering (AHE) maintenance record. It captures a
small, falsifiable ActionAnything runtime hardening change; it does not add an
Agent Harness to the product.

## Observation

`ActionRuntime` previously treated any truthy confirmation return value as an
approval. A handler returning a non-empty error string, `1`, or another truthy
object could therefore allow a policy-gated action. The runtime also accepted
duck-typed objects with action-like attributes. Such a value can claim a
low-risk click/type action and bypass the canonical `Action` constructor's
immutable parameters and trusted risk floor.

The execution-budget batch path made the latter more subtle: its one extra
candidate is inspected for an ID before it is passed to the ordinary execution
hook, so validation only inside `_execute()` would leave a gap.

## Hypothesis

If the base runtime admits only exact `Action` values, rebuilds isolated
canonical immutable snapshots before policy, confirmation, budget, recorder,
executor, or overridable execution hooks run, and treats only the literal
built-in `True` as confirmation, malformed or tampered integration input and
ambiguous confirmation values cannot reach an executor or weaken another
policy's decision.

The hypothesis is falsified if a truthy non-`True` confirmation result causes
an executor call, or if a duck-typed/subclass action reaches policy, budget,
recording, a legacy override, or an executor.

## Scope

- Require `type(action) is Action` and rebuild its public representation at
  direct, private, budgeted-batch, and unbudgeted-batch runtime boundaries.
- Give each composed policy its own canonical snapshot so object-internal
  mutation cannot downgrade a later policy's view of an action.
- Interpret confirmation as approved only when `result is True`.
- Add deterministic regression tests for strings, integers, arbitrary truthy
  objects, a truthiness trap, duck-typed objects, `Action` subclasses,
  tampered/unconstructed exact objects, hook mutation, scalar subclasses, a
  budget-exhausted extra candidate, a legacy `execute()` override, and a
  risk-downgrading policy preceding `RiskPolicy`.
- Document the intentional 0.x compatibility change and the integration
  normalization path.

This change does not alter policy rules, action serialization, CLI `--yes`,
executor permissions, or application-owned confirmation UI. It preserves the
budget limit/reservation semantics for canonical actions; non-canonical values
now fail before budget admission, trace recording, or execution.

## Actual local validation

Using a supported Python 3.12 interpreter with `PYTHONPATH=src` and a
temporary bytecode-cache directory:

```bash
python -m unittest tests.test_runtime tests.test_cli -v
python -m unittest discover -s tests -v
python -m compileall -q src
git diff --check
git diff --cached --check
```

Results: **54 targeted runtime/CLI tests passed** and **105 full offline tests
passed**. Source compilation, working-tree format, and staged-format checks
passed. The tests assert zero policy, confirmation, recorder, budget, or
executor calls for invalid values where relevant.

## Independent review

An independent read-only review found that a simple `isinstance` check would
still admit `Action` subclasses, and that validating only `_execute()` would
miss the one-extra-candidate budget path and the legacy unbudgeted override
path. The implementation was tightened to exact-type admission plus snapshot
reconstruction at all of those boundaries. A follow-up review showed that an
exact frozen instance can still be altered with `object.__setattr__`, that a
confirmation hook could otherwise mutate the same object later passed to an
executor, and that one custom policy could downgrade the shared value a later
policy receives. Regressions now prove the runtime restores the click/type
risk floor for tampered and unconstructed exact instances, isolates policy,
confirmation, and execution snapshots, and removes scalar-subclass behavior.
The review also requested a truthiness trap; the regression uses an object
whose `__bool__` raises, proving the runtime does not coerce a confirmation
value.

## Residual risks and next question

This protects the base runtime's Python-object intake boundary, not arbitrary
code running in the same process: such code can still call an executor directly
or deliberately override the public runtime method. Exact `Action` admission
intentionally rejects subclass-based action integrations; callers should use
composition or reconstruct a canonical `Action` through its documented
constructor.

The next practical question is whether the existing programmatic browser
request-method containment policy needs a separately reviewed CLI surface.
Any such option must stay trusted deployment configuration, separate from
action plans, provider payloads, and trace data.
