# Releasing `mpl_inspector`

This project is set up to support both direct GitHub installs and PyPI publishing.

## Current install paths

Local editable install:

```bash
python -m pip install -e .
```

GitHub install after the repo is pushed:

```bash
python -m pip install "mpl_inspector @ git+https://github.com/papayuh/mpl_inspector.git"
```

If/when the first PyPI release succeeds:

```bash
python -m pip install mpl-inspector
```

`pip` normalizes `_` and `-`, so `mpl_inspector` and `mpl-inspector` map to the same project name on PyPI.

## First PyPI release

Recommended path: Trusted Publishing from GitHub Actions.

1. Create or log in to your PyPI account.
2. Create a new pending project by adding a Trusted Publisher for this repository in PyPI.
3. On PyPI, configure:
   - Owner: `papayuh`
   - Repository: `mpl_inspector`
   - Workflow name: `Publish`
   - Environment name: `pypi`
4. Push this repository to GitHub.
5. Create a GitHub Release, for example `v0.3.0`.
6. Publishing will run automatically through `.github/workflows/release.yml`.

## Local preflight before releasing

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m build
python -m twine check dist/*
```

## Versioning checklist

Before each release:

1. Update `version` in [pyproject.toml](/Users/diego/Downloads/mpl_inspector/pyproject.toml).
2. Commit the version change.
3. Tag or create a GitHub Release with the same version, e.g. `v0.3.1`.
4. Verify the publish workflow succeeds.

## Name availability

At the time of setup, `pip index versions mpl-inspector` returned no matching distribution, so the name appears available for a first upload. That is not a reservation; PyPI availability is only effectively claimed when the first release is uploaded.
