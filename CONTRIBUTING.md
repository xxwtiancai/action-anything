# Contributing to ActionAnything

Thanks for helping make AI agent actions safer and easier to inspect.

## Development setup

```bash
git clone https://github.com/xxwtiancai/action-anything.git
cd action-anything
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
```

The core package has no runtime dependencies. The ``dev`` extra installs the
Draft 2020-12 validator used by the schema-contract tests. Install the optional
browser extra only when working on the Playwright executor:

```bash
python -m pip install -e '.[dev,browser]'
playwright install chromium
```

## Contribution workflow

1. Open an issue for substantial API or security changes.
2. Fork the repository and create a focused branch from `main`.
3. State a falsifiable hypothesis, the non-goals, and the relevant safety
   boundary before making a substantial change.
4. Add tests for new behavior and failure paths.
5. Run the full test suite and `git diff --check`.
6. Open a pull request that explains the motivation, behavior, actual
   validation, and residual risk.

## Lightweight AHE maintenance loop

ActionAnything uses **Agentic Harness Engineering (AHE)** as a development
discipline, not as a request to add an Agent Harness feature to the package.
For each substantive iteration, follow this small loop:

1. Observe the affected component and current evidence.
2. Form a testable hypothesis and state the risk boundary.
3. Make the smallest independently reviewable change.
4. Run targeted, deterministic checks and report only the checks actually run.
5. Record the result, residual risks, and next question in the PR or a concise
   note under `docs/maintainer-iterations/`.

The first draft record is
[`001-action-intake-browser-containment.md`](docs/maintainer-iterations/001-action-intake-browser-containment.md).
See [`AGENTS.md`](AGENTS.md) for the component map and escalation boundaries.

For Adapter work, keep the boundary explicit: adapters normalize documented
provider payloads into `Action` values. The embedding application owns provider
SDK calls, API keys, prompts, safety-review flows, and deployment policy.

Use concise Conventional Commit messages when practical:

```text
feat: add Selenium executor
fix: reject malformed navigation URLs
docs: explain custom policy composition
test: cover denied batch execution
```

## Pull request checklist

- The change has one clear purpose.
- Public behavior is documented.
- New behavior includes tests.
- Safety-sensitive defaults remain conservative.
- Substantive changes include the observed baseline, hypothesis, checks actually
  run, residual risk, and a next question (in the PR or iteration note).
- Adapter changes do not silently add model calls, credentials, or automatic
  acknowledgement of provider safety checks.
- Logs and examples contain no credentials or private data.
- The test suite passes on a supported Python version.

## Security changes

Do not open a public issue for a vulnerability. Follow [SECURITY.md](SECURITY.md)
and use GitHub's private vulnerability reporting flow.
