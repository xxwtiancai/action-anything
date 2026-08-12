# Contributing to ActionAnything

Thanks for helping make AI agent actions safer and easier to inspect.

## Development setup

```bash
git clone https://github.com/xxwtiancai/action-anything.git
cd action-anything
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

The core package has no runtime dependencies. Install the optional browser extra
only when working on the Playwright executor:

```bash
python -m pip install -e '.[browser]'
playwright install chromium
```

## Contribution workflow

1. Open an issue for substantial API or security changes.
2. Fork the repository and create a focused branch from `main`.
3. Add tests for new behavior and failure paths.
4. Run the full test suite and `git diff --check`.
5. Open a pull request that explains the motivation, behavior, and validation.

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
- Logs and examples contain no credentials or private data.
- The test suite passes on a supported Python version.

## Security changes

Do not open a public issue for a vulnerability. Follow [SECURITY.md](SECURITY.md)
and use GitHub's private vulnerability reporting flow.

