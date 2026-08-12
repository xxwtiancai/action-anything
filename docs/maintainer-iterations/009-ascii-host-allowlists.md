# Iteration 009: ASCII host allowlists

**Status: local validation complete; independent review and remote CI pending.**
This is an Agentic Harness Engineering (AHE) maintenance record. It captures a
small, falsifiable ActionAnything maintenance iteration; it does not add an
Agent Harness to the product.

## Observation

The domain policy used Python's built-in IDNA codec to transform Unicode host
spellings before matching. Its legacy mapping can turn `faß.de` into `fass.de`,
while a modern browser treats `faß.de` as the distinct hostname
`xn--fa-hia.de`. An allowlist could therefore authorize one spelling in policy
code while a browser canonicalizes the requested URL differently.

## Hypothesis

If standard navigation and allowlist configuration accept only explicit ASCII
hostnames, with internationalized domains supplied as reviewed Punycode
A-labels, the policy and pre-execution browser boundary cannot silently widen
an allowlist through Python's legacy Unicode mapping.

The hypothesis is falsified if a Unicode URL or allowlist entry reaches an
allow decision, or if a configured ASCII Punycode hostname cannot be matched
exactly and case-insensitively.

## Scope

- Reject non-ASCII URL hosts in standard public-HTTP and allowlist checks.
- Require trusted allowlist configuration to use ASCII/Punycode A-labels.
- Preserve existing ASCII, subdomain, IP-literal, malformed-port, and legacy
  numeric IPv4 defenses.
- Cover policy and Playwright pre-execution/request-route behavior with
  deterministic offline tests.
- Do not add an IDNA dependency, alter the generic `Action` URL syntax, make a
  claim about browser homograph safety, or resolve DNS.

## Actual local validation

Using a supported Python 3.12 interpreter with `PYTHONPATH=src` and a temporary
bytecode-cache directory:

```bash
python -m unittest tests.test_policy tests.test_executors tests.test_cli -v
python -m unittest discover -s tests -v
python -m compileall -q src
git diff --check
git diff --cached --check
```

Results: **35 targeted tests passed** and **70 offline tests passed**. Source
compilation and the staged format checks passed. The targeted suite
covers Unicode U-label rejection, configuration rejection, exact
case-insensitive Punycode matching, subdomains, request routing, current-page
containment, and the CLI's real-executor construction path.

The prior `faß.de` regression was also checked directly: the standard policy
with an `fass.de` allowlist now returns `deny`, the Playwright precheck returns
`False`, and explicit `xn--fa-hia.de` remains accepted.

## Residual risks

ASCII/Punycode comparison prevents this Unicode mapping mismatch but does not
make a domain semantically trustworthy. Punycode can still be visually
confusing, and DNS rebinding, proxy behavior, browser parsing, server intent,
credentials, confirmation, and application authorization require independent
controls. Real Chromium behavior has not been exercised in this local offline
test run.
