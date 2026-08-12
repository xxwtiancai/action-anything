# Iteration 014: Canonical schema intake and bounded metadata

**Status: local validation and independent review complete; remote CI pending.**
This AHE record tracks one integrated ActionAnything schema-hardening change.
It does not add a product Agent Harness.

## Observation

The action schema accepted Python subclasses of JSON scalar types. A `str`
subclass could expose one base URL to `Action` storage and another through
`__str__` when policy code inspected it. An `int` subclass could similarly
override `__int__` and cause the old runtime snapshot path to lower a tampered
risk value. The runtime also rebuilt snapshots through `action.to_dict()`, an
instance attribute that in-process code could replace through Python object
internals.

This left inconsistent views between schema intake, `PolicyEngine`, the base
runtime, and an executor. It is an in-process integration boundary, not a
claim that arbitrary code in the same process is sandboxed.

## Hypothesis

If `Action` and `ActionResult` convert accepted scalar subclasses to their
underlying built-in JSON values before validation and storage, retain existing
frozen-container behavior, and runtime/policy snapshots re-enter `Action(...)`
from fields rather than `to_dict()`, all built-in consumers will see one stable
value. If `Action.metadata` additionally tracks raw container identity before
copying, a 64-container cap and cycle rejection can remain correct after
mapping normalization.

The hypothesis is falsified if a policy can authorize the base value of a
divergent URL differently from the stored value, a custom scalar bypasses a
bound, or a tampered `to_dict` changes the action sent to an executor.

## Scope

- Normalize strings, integers, finite floats, mapping keys, metadata, action
  parameters, result fields, and result output to built-in JSON scalars.
- Reject mapping-key collisions exposed only after string normalization.
- Rebuild runtime and per-policy snapshots directly from `Action` fields,
  never from an object-provided `to_dict()` method.
- Bound `Action.metadata` to 64 mapping/list/tuple containers, reject direct
  and indirect cycles using raw object identity, and normalize excessively
  nested plan-decoder failures at the CLI boundary.
- Use structural schema diagnostics that do not echo attacker-controlled field
  names, values, nested keys, or parser exception chains.
- Add deterministic regressions for divergent string, integer, float, key,
  risk, serializer, metadata-depth, metadata-cycle, and diagnostic behavior.

This does not add a new action type, change confirmation defaults, expand
executor permissions, make arbitrary in-process code safe, or define new
depth/cycle limits for `ActionResult.output`. Trace-input normalization and
arbitrary exceptions from custom applications or executors remain separate
boundaries.

This is a stacked schema integration: it incorporates the related bounded
metadata and safe-diagnostic intake work because scalar canonicalization copies
mapping values. The merged implementation must use raw mapping/list/tuple
identity before copying; independently merging an older implementation that
tracks copied mapping identity would reintroduce recursive failure behavior.

## Actual validation

Using the bundled supported Python 3.12 interpreter with `PYTHONPATH=src` and
a temporary bytecode-cache directory:

```bash
python -m unittest tests.test_actions tests.test_policy tests.test_runtime tests.test_cli -v
python -m unittest discover -s tests -v
python -m compileall -q src
git diff --check
git diff --cached --check
```

Results: **95 targeted tests passed** and **119 full offline tests passed**.
Source compilation, the working-tree format check, and the selective staged
format check all passed.

The regressions cover a divergent URL scalar observed by `PolicyEngine`,
integer/float bound bypass attempts, normalized key alias collisions, injected
`to_dict()` and risk tampering, direct and indirect metadata cycles, the
64/65-container boundary through both direct construction and `from_dict`, a
deep-decoder failure normalized by the CLI, safe diagnostic text and exception
chains, and preserved root-mapping contracts.

## Independent review

Independent review found three integration hazards before final validation:

- tracking the identity of a normalized mapping copy would miss self-cycles;
- a scalar-normalization refactor briefly weakened the required mapping shape
  for metadata and result output; and
- a deep JSON fixture tested a decoder behavior that was interpreter-specific.

The implementation now tracks original container identity before copying,
retains required root mappings, and has separate deterministic schema-depth
and decoder-failure regressions. The final read-only security review found no
remaining P0/P1 issue in the changed boundaries.

## Residual risks and next question

Normal JSON and built-in Python values retain their behavior. Integrations that
relied on a scalar subclass retaining custom conversion, comparison, hashing,
or serialization behavior now need to pass ordinary JSON-compatible values.
Arbitrary code in a process can still call executors directly, bypass schema
admission, or override application hooks. `ActionResult.output` intentionally
does not yet impose this metadata depth/cycle contract; a malformed custom
executor output is normalized as an executor failure by the base runtime.

The next question is whether `ActionResult.output` needs the same explicit
depth/cycle contract as untrusted action metadata, without conflating trace
input normalization with the in-memory result API.
