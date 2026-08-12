# Governance

## Project model

ActionAnything is currently an owner-led open-source project. The repository
owner is the initial maintainer and is accountable for releases, security
response coordination, and final decisions. Code ownership is recorded in
[.github/CODEOWNERS](.github/CODEOWNERS).

This lightweight model is intentional while the project is pre-1.0. It keeps
decisions clear without treating contribution volume as a substitute for review
of safety-sensitive changes.

## Roles

### Maintainers

Maintainers review and merge changes, set release policy, moderate project
spaces, and protect the project's users and contributors. They should explain
material decisions in the relevant issue, pull request, release note, or
security advisory when it is safe to do so.

### Contributors

Anyone may propose issues, documentation, tests, code, examples, or design
feedback. Contributions are evaluated on their technical quality, maintenance
cost, compatibility, and safety impact. A contribution does not create a
guarantee of merge, roadmap priority, or maintainer status.

## How decisions are made

For routine changes, a maintainer decides after reviewing the pull request and
its validation. For material decisions—such as public API changes, new action
kinds or executors, policy-default changes, trace handling, security fixes, and
release changes—the maintainer will seek relevant feedback when practical and
record the rationale.

When reasonable contributors disagree, the project favors the option that is
most conservative about user authority, data exposure, and long-term
maintenance. The maintainer makes the final call for an early-stage project.

## Maintainer changes

New maintainers may be invited based on sustained, trustworthy contributions to
code quality, reviews, documentation, or community stewardship. The repository
owner records a maintainer addition or removal in a public repository change
when it is safe to do so. Access is removed promptly when a maintainer steps
down or no longer needs it.

## Releases and compatibility

Maintainers release only changes that have the required tests and documentation
for their risk level. Before 1.0, APIs may change; changes with meaningful user
impact should include migration guidance in the pull request or release notes.
Security fixes follow [SECURITY.md](SECURITY.md) rather than public discussion
while details are embargoed.

## Conduct and conflicts

All participants must follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
Maintainers must recuse themselves from a conduct or security decision when
they are directly involved. The remaining maintainer(s), or GitHub's reporting
process when no impartial maintainer is available, will handle the matter.
