# Releasing `e3dc-ess-modbus`

Publishing a GitHub release publishes the package to PyPI. Nothing else does.

## Release tags

A release tag is the bare version, such as `0.1.5` or `1.0.0`, without a leading `v`. The workflow sets the package version from it. The `pypi` environment only accepts tags that match `*.*.*`.

## Releasing

1. Check that the `CI` workflow is green on `main`.
2. On GitHub, draft a new release:
   - **Tag:** the new version, such as `0.1.5`, created on `main`.
   - **Title:** the version.
   - **Description:** the release notes.
3. Publish the release. This starts the `Publish to PyPI` workflow, which runs the tests, sets the version from the tag, and builds the package.
4. In the Actions tab, approve the `publish` job. It waits for approval because it runs in the `pypi` environment. Once approved, it publishes to PyPI through trusted publishing.

## One-time PyPI setup

On PyPI, the trusted publisher for `e3dc-ess-modbus` must name:

- **Owner:** `AlCalzone`
- **Repository:** `e3dc-ess-modbus`
- **Workflow:** `publish.yml`
- **Environment:** `pypi`

For the first release, add it as a pending publisher, because the project doesn't exist on PyPI yet.
