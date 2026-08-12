# Security Policy

ActionAnything sits between model output and real actions. Treat policy bypasses,
unsafe defaults, credential exposure, and sandbox escapes as security issues.

## Supported versions

Until the first stable release, security fixes are applied to the latest code on
`main`. Earlier pre-1.0 revisions are not supported.

## Reporting a vulnerability

Please do not create a public issue or include exploit details in a public pull
request. Use GitHub's **Security → Report a vulnerability** flow for this
repository so the report can be reviewed privately.

Include, when possible:

- the affected commit or version;
- the action plan and policy configuration needed to reproduce the issue;
- expected and observed behavior;
- impact and whether real credentials or external systems were involved;
- a minimal reproduction with secrets removed.

## Deployment guidance

- Run real executors in an isolated browser profile or sandbox.
- Use allowlists and least-privilege credentials.
- Keep human confirmation for external and irreversible effects.
- Do not use `--unsafe-trace` with production or personal data.
- Review recorded actions and screenshots before sharing traces.
- Assume web content may contain prompt injection attempts.

