# Support

ActionAnything is an early-stage, community-maintained project. The maintainer
will make a reasonable effort to help with supported, reproducible issues, but
the project does not offer a response-time or availability guarantee.

## What we can help with

- Using the maintained code on `main` and documented CLI or Python APIs.
- Reproducible defects in the core runtime, policies, trace handling, and
  optional Playwright executor.
- Focused feature proposals that explain the user need and safety impact.
- Documentation corrections and contribution questions.

## What is outside project support

- Operating an autonomous agent in production or making decisions on your
  behalf.
- Recovering data, credentials, or actions performed by a third-party website.
- Debugging private infrastructure, proprietary models, or unshared custom
  integrations.
- Guaranteeing a remote website's behavior, availability, or compatibility.

## Before opening an issue

1. Read the [README](README.md), [architecture overview](docs/architecture.md),
   and relevant command help.
2. Search existing issues for the same question or behavior.
3. Reproduce against the latest `main` commit when practical.
4. Remove tokens, passwords, personal data, raw screenshots, and unredacted
   traces from the report.

## Where to ask

- **A reproducible defect:** use the Bug report form.
- **A focused improvement:** use the Feature request form.
- **A security vulnerability:** follow [SECURITY.md](SECURITY.md). Do not put
  exploit details in a public issue or pull request.
- **A conduct concern:** follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

For a usage question that is not a defect, first consult the documentation and
existing issues. If it exposes a documentation gap, a small documentation issue
or pull request is welcome.

## Helpful information for bug reports

Include the ActionAnything version or commit, Python version, operating system,
executor type, a minimal redacted action plan, the policy configuration, exact
commands, and expected versus observed behavior. Please use test credentials
only; an issue tracker is not a secure channel for traces or browser artifacts.
