# Releasing `e3dc-ess-modbus`

This document describes how to release a new version of `e3dc-ess-modbus` to PyPI.

## Tagging Convention

> [!IMPORTANT]
> **Release tags must be bare semantic versions without a leading `v`** (e.g. `0.1.5`, `1.0.0`).
> Do not use `v`-prefixed tags like `v0.1.5`.

Release tags are directly substituted into `pyproject.toml` during the release workflow to set the package version according to PEP 440.

## Release Process

1. **Verify CI**: Ensure that the `CI` workflow is green on the `main` branch.
2. **Draft a GitHub Release**:
   - Go to GitHub Releases: **Draft a new release**.
   - **Choose a tag**: Enter the new version number as a bare tag (e.g. `0.1.5`).
   - **Target**: `main`.
   - **Title**: Enter the version number (e.g. `0.1.5`).
   - **Description**: Provide release notes / changelog.
3. **Publish the Release**:
   - Click **Publish release**.
   - The `.github/workflows/publish.yml` workflow will automatically trigger, build the wheel and source distribution, and publish the package to PyPI via Trusted Publishing.
