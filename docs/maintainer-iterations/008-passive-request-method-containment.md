# Iteration 008: Passive browser request containment

**Status: local validation complete; independent review and remote CI pending.**
This is an Agentic Harness Engineering (AHE) maintenance record. It describes
one small, falsifiable ActionAnything improvement; it does not add a model
Harness to the product.

## Observation

`PlaywrightExecutor` already confines requests to public HTTP(S) URLs under a
trusted domain allowlist. That boundary still allowed every HTTP method at an
allowed host. A confirmed click, type, or Enter key can therefore trigger an
application-side `POST`, `PUT`, `PATCH`, or `DELETE` without an executor-level
network-method boundary.

## Hypothesis

If the Playwright route allows only `GET` by default, and requires a trusted
explicit allowlist for every other standard method, ordinary browser navigation
remains available while common network writes are blocked before they leave the
browser context.

The hypothesis is falsified if a default-route test continues an allowlisted
write method, an invalid request method causes an unhandled exception, or an
explicit method grant accidentally bypasses the URL/domain checks.

## Scope

- Add trusted `allowed_request_methods` configuration to `PlaywrightExecutor`.
- Default to immutable `{GET}` and fail closed for unknown, malformed,
  tunnel, diagnostic, or additional standard methods unless trusted
  configuration explicitly permits them.
- Keep the existing HTTP(S), public-host, and domain checks after method
  admission.
- Add deterministic fake-route tests; do not change the action protocol,
  policy engine, CLI, trace format, adapters, or confirmation defaults.

The CLI deliberately receives no request-method flag in this iteration. It
therefore retains the executor's `GET` default; embedding applications own any
explicit method expansion in Python configuration.

## Actual local validation

Using a supported Python 3.12 interpreter with `PYTHONPATH=src` and a temporary
bytecode-cache directory:

```bash
python -m unittest tests.test_executors -v
python -m unittest discover -s tests -v
python -m compileall -q src
git diff --check
```

Results: **16 executor tests passed** and **71 offline tests passed**. The
targeted tests cover the default `GET` boundary, all default-denied standard
methods, explicit grants, malformed route methods, route-property failures,
domain containment after a method grant, immutable configuration snapshots, and
an explicit empty deny-all configuration. Compilation and diff checks passed.

Remote CI and a real isolated Chromium route test remain separate evidence;
mock routes do not prove browser or server behavior.

## Residual risks

`GET` is not a guarantee of read-only business semantics, and a
blocked asynchronous subrequest may not make a Playwright action fail. DNS,
server behavior, credentials, CSRF defenses, business authorization, browser
isolation, and human confirmation remain the embedding application's
responsibility. Explicitly allowing a write-capable method expands the browser
egress boundary and must be reviewed by that application.

The route callback is also not a complete browser sandbox: a caller that adds
or changes browser-context routes owns the resulting interception behavior.
