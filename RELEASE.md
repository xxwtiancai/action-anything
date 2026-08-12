# Releasing ActionAnything

ActionAnything releases are built in GitHub Actions from a published GitHub
Release. The workflow validates the version, builds the source distribution and
wheel, checks their metadata, attaches them to the GitHub Release, and records
build provenance. PyPI publishing is deliberately disabled until a maintainer
completes the trusted-publishing setup below.

## First-time setup

1. Create a GitHub environment named `pypi` and require an appropriate
   maintainer to approve deployments. Keep it limited to release maintainers.
2. Configure a PyPI trusted publisher for this repository:
   - owner: `xxwtiancai`;
   - repository: `action-anything`;
   - workflow: `release.yml`;
   - environment: `pypi`.
3. Set the repository variable `PYPI_PUBLISH_ENABLED` to `true` only after the
   trusted publisher and environment protections are in place.

This workflow uses GitHub OIDC rather than a long-lived PyPI token. PyPI's
[trusted-publishing guide](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
has the current configuration details.

## Cut a release

1. Choose the next semantic version.
2. Update the package version in `pyproject.toml` and `src/actionanything/__init__.py`.
3. Move the relevant entries from `CHANGELOG.md`'s **Unreleased** section into
   a versioned section.
4. Run the full verification locally:

   ```bash
   python -m unittest discover -s tests -v
   python -m pip install --upgrade build twine
   python -m build
   python -m twine check dist/*
   ```

5. Commit the release preparation, then create and push an annotated tag whose
   name exactly matches the package version:

   ```bash
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   git push origin vX.Y.Z
   ```

6. In GitHub, create a Release for that tag and select **Publish release**.
   Do not publish a release if the tag and package version differ; the workflow
   rejects that mismatch.
7. Review the Release workflow. It always uploads the checked distributions as
   GitHub Release assets. If the PyPI gate is enabled, approve the `pypi`
   environment to publish through the trusted publisher.

## Verify a published release

Download the distributions from the GitHub Release and verify their provenance:

```bash
gh release download vX.Y.Z --repo xxwtiancai/action-anything --dir dist
gh attestation verify dist/* --owner xxwtiancai
```

Artifact attestations show the repository, commit, workflow, and event that
produced a release asset. See GitHub's
[artifact-attestation documentation](https://docs.github.com/actions/concepts/security/artifact-attestations)
for verification options and limits.

## Correcting a bad release

Do not overwrite a published PyPI version. Mark the GitHub Release as a
prerelease or draft if appropriate, document the issue in the changelog, and
publish a corrected patch version. For a security issue, follow
[SECURITY.md](SECURITY.md) and coordinate the disclosure before publishing a
fix.
