# 007 · Exact selector allowlist policy

**Status:** local verification and independent review complete; remote CI
pending.

## Observation

An allowed domain is necessary but does not identify which control a model may
operate. Canonical click actions can use browser coordinates and type actions
can target the currently focused input, so a selector-only policy must deny
those unaddressable forms or it becomes bypassable.

## Falsifiable hypothesis

If applications opt into a trusted exact selector allowlist for click and type
actions, then only byte-for-byte matching selector actions can continue to
confirmation; every coordinate click, focused type, or non-matching selector
is denied before the executor.

## Small scope

- Added `SelectorAllowlistPolicy` and a strict configuration helper.
- Kept it opt-in: `PolicyEngine.standard()` remains compatible, while an
  explicitly empty selector collection denies all click/type targets.
- Performed exact string membership only: no stripping, case folding, locator
  parsing, wildcard, regex, or escape normalization.
- Returned `confirm` on a match rather than `allow`; selector text is target
  admission evidence, not a claim of page or business safety.

No DOM inspection, provider adapter changes, CLI selector flags, selector-to-
domain binding, model I/O, or executor changes were added.

## Verification

Run from the repository root with a supported Python environment:

```bash
PYTHONPATH=src python -m unittest tests.test_policy -v
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src
git diff --check
```

Actual local result with Python 3.12: 21 policy tests and 73 full offline tests
passed; compilation and `git diff --check` passed. Coverage includes exact
click/type matches, whitespace/prefix/combined/XPath near-misses,
coordinate/focused bypass attempts, empty and invalid configuration, immutable
configuration, standard-policy compatibility, and a runtime assertion that
denied coordinate/focused proposals do not reach the confirmation handler or
executor.

## Residual risk and next question

An exact selector does not prove a unique element, stable DOM, current origin,
business semantics, or a safe post-click navigation. Applications still need
confirmation, browser/domain containment, isolated accounts, and their own
business authorization rules. Coordinate-based provider actions are deliberately
incompatible with this selector-specific policy.

The next question is whether a separately reviewed origin-bound target policy
can add useful guarantees without pretending that a browser page's DOM is a
stable authorization boundary.
