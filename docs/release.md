# Releasing OpenTorus

This page is the operating manual for cutting a release: what to check, how the
version and the changelog are handled, how the tag-triggered workflow behaves,
and how to undo a release that went wrong. It is written for the person holding
the tag, not for contributors in general -- feature work never touches any of
this (see "Versioning policy").

The pipeline lives in `.github/workflows/release.yml`; the everyday packaging
gate (build, twine, clean-venv installs) runs on every push and pull request in
the `build` job of `.github/workflows/lint.yml`, so a release is never the first
time the wheel is installed.

```
  git tag vX.Y.Z  -->  test  -->  build  -->  install-smoke  --+
                                    |                          |
                                    +------->  sbom  ----------+--> publish (PyPI, gated)
                                    |                          |
                                    +------->  provenance -----+--> github-release (draft, gated)
```

## Release checklist

1. `main` is green: the `tests` and `lint` workflows passed on the commit you
   intend to release (the `build` job of `lint` is the packaging gate).
2. `CHANGELOG.md`: move everything under `## [Unreleased]` into a new
   `## [X.Y.Z] - YYYY-MM-DD` section, leave an empty `## [Unreleased]` above
   it, and read the section as a user would (see "CHANGELOG expectations").
3. Bump `__version__` in `src/opentorus/__init__.py` to `X.Y.Z` -- this is the
   only place; `pyproject.toml` reads it dynamically and
   `tests/test_version.py` pins that.
4. Run the package verification commands below locally, all of them.
5. Open a pull request with exactly the changelog and version changes
   ("release X.Y.Z"), let CI pass, merge it.
6. Tag the merge commit on `main`: `git tag -a vX.Y.Z -m "OpenTorus X.Y.Z"` and
   `git push origin vX.Y.Z`. The tag must equal `v` + `__version__`; the
   workflow refuses anything else.
7. Watch the `release` workflow. With publishing disabled (the default) it ends
   after `install-smoke`, `sbom` and `provenance`; download the `dist` and
   `sbom` artifacts if you want to inspect them.
8. With publishing enabled: confirm the PyPI page shows the new version, then
   open the *draft* GitHub release, paste the changelog section into the body,
   check the attached files (`dist/*`, `sbom.spdx.json`) and publish it.
9. Verify from a clean machine or venv: `pip install opentorus==X.Y.Z` and
   `opentorus --version`.

## Versioning policy

OpenTorus follows Semantic Versioning. While the major version is 0 the usual
pre-1.0 reading applies: the minor version may carry breaking changes, and the
patch version carries fixes and additive features. Breaking changes are still
called out explicitly in the changelog with a migration note; nothing is
silently renamed.

The version is single-sourced in `src/opentorus/__init__.py`
(`__version__ = "X.Y.Z"`). `pyproject.toml` declares `dynamic = ["version"]`
and reads that attribute; the CLI prints it for `opentorus --version`. Never
bump the version in a feature or fix pull request. The bump is part of the
release pull request only, so that the tag, the changelog header and
`__version__` always change together and `main` between releases carries the
last released version.

## CHANGELOG expectations

`CHANGELOG.md` follows Keep a Changelog. `## [Unreleased]` collects entries as
they land; a release turns it into `## [X.Y.Z] - YYYY-MM-DD` (ISO date) and
starts a fresh empty `## [Unreleased]`.

House style, worth keeping because it is what makes the log readable months
later:

- Each version section opens with a few paragraphs of *narrative*: what was
  observed, what evidence pointed to it, why the change is the right one. The
  ledgers OpenTorus writes (`actions.jsonl`, usage records) are the usual
  source of that evidence; cite counts when you have them.
- Then `### Fixed`, `### Added`, `### Changed`, `### Removed` lists as needed.
  Bullets are **bold full sentences** stating the behaviour, followed by a
  short rationale clause -- for example
  `- **A repaired argument name stays visible in the ledger**, so the slip
  rate remains measurable after the slip stops hurting.`
- Behaviour that touches claims, evidence, proofs or reports states how it
  preserves the epistemic invariants (CONTRIBUTING.md).

## Package verification commands

The release workflow runs these; run them locally before tagging so the tag
push is a confirmation, not an experiment. From the repository root:

```
ruff check .
ruff format --check .
mypy src
pytest

python -m build
twine check dist/*
ls dist/*.whl dist/*.tar.gz             # both must exist

# Clean-venv wheel install + CLI smoke
python -m venv /tmp/ot-wheel
/tmp/ot-wheel/bin/pip install dist/*.whl
/tmp/ot-wheel/bin/opentorus --version
/tmp/ot-wheel/bin/opentorus --help
( cd "$(mktemp -d)" && /tmp/ot-wheel/bin/opentorus init \
    && /tmp/ot-wheel/bin/opentorus config set quality.test_command null \
    && /tmp/ot-wheel/bin/opentorus doctor --json )

# Import without optional deps: the CLI must not pull in textual
/tmp/ot-wheel/bin/python -c "import sys, opentorus.cli; assert 'textual' not in sys.modules"

# Clean-venv sdist install + CLI smoke
python -m venv /tmp/ot-sdist
/tmp/ot-sdist/bin/pip install dist/*.tar.gz
/tmp/ot-sdist/bin/opentorus --version
/tmp/ot-sdist/bin/opentorus --help

# Dashboard extra
/tmp/ot-wheel/bin/pip install "$(ls dist/*.whl)[dashboard]"
/tmp/ot-wheel/bin/python -c "import textual"
/tmp/ot-wheel/bin/python -c "import sys, opentorus.cli; assert 'textual' not in sys.modules"
```

`config set quality.test_command null` is there because a clean venv has no
pytest and `doctor` reports a missing test runner as a failed environment
check; the smoke wants to know that the *package* works, not that the venv is
a development environment. Remove `dist/` and `build/` afterwards; neither is
tracked.

## Trusted-publishing setup

Publishing uses PyPI trusted publishing (OpenID Connect): GitHub mints a
short-lived token for the workflow run and PyPI accepts it because the
project has registered this repository, workflow and environment as a
publisher. No API token is stored anywhere. Set it up once:

1. On PyPI, open the `opentorus` project (or "pending publishers" for a
   first release), Publishing, add a GitHub publisher with owner
   `maximilianbehr`, repository `OpenTorus`, workflow `release.yml`,
   environment `pypi`. All four must match the workflow exactly.
2. On GitHub, Settings > Environments, create `pypi`. Optionally add
   required reviewers -- the `publish` job then pauses until one of them
   approves, which is a cheap second pair of eyes on every upload.
3. On GitHub, Settings > Secrets and variables > Actions > Variables, add the
   repository variable `OPENTORUS_RELEASE_PUBLISH` with value `true`. This
   enables both the `publish` and the `github-release` jobs. Until it exists
   (or holds anything else) both jobs are skipped and a tag push is a dry
   run.

To pause publishing again, delete the variable or set it to `false`; the rest
of the workflow keeps running so tags stay verified.

## Cutting a release

Push an annotated tag `vX.Y.Z` that points at a commit on `main` whose
`__version__` is `X.Y.Z`. The workflow then runs, in order:

- `test`: ruff, ruff format, mypy, pytest on Python 3.12.
- `build`: `python -m build`, `twine check`, the tag/version consistency
  check (the version is read *textually* from `src/opentorus/__init__.py`, so
  it cannot be fooled by whatever `opentorus` the runner might import), and
  the `dist` artifact upload.
- `install-smoke`: wheel and sdist into two clean venvs, `--version`,
  `--help`, `init` + `doctor`, the import-without-textual assertion, the
  dashboard extra.
- `sbom`: an SPDX JSON software bill of materials of the installed wheel and
  its dependency closure (`sbom.spdx.json` artifact).
- `provenance`: a build provenance attestation for `dist/*`, visible under
  the repository's Attestations tab and verifiable with
  `gh attestation verify dist/opentorus-X.Y.Z-py3-none-any.whl --owner maximilianbehr`.
- `publish` (gated): upload to PyPI via trusted publishing.
- `github-release` (gated): a *draft* GitHub release named after the tag with
  `dist/*` and `sbom.spdx.json` attached. Publishing the draft is a manual
  step, so release notes are always read by a person first.

## Rollback and yanking

Nothing on PyPI can be overwritten: a version, once uploaded, is permanent
even after deletion, and the same version number can never be reused. That
leaves two tools:

- **Yank** the release on PyPI (project page > Manage > Releases > Options >
  Yank, with a reason). A yanked release stays installable when pinned
  exactly (`opentorus==X.Y.Z`) but is skipped by unpinned installs and
  resolvers, which is exactly what you want when the release is broken but
  someone's lockfile depends on it. Yank when the release is unusable or
  harmful (broken install, wrong dependencies, an epistemic regression);
  do not yank for an ordinary bug -- ship a patch release instead, since
  yanking does not repair anyone who already installed it.
- **Patch release**: fix on `main`, follow the checklist, tag `vX.Y.(Z+1)`.
  This is the normal path for anything short of "must not be installed".

On the GitHub side, the release is created as a draft, so before you publish
it you can simply edit or delete the draft. A published GitHub release can be
edited or deleted from the releases page.

Git tags: deleting or moving a tag that has been pushed is disruptive
(clones keep the old tag, the attestation and PyPI upload reference the
original commit) and the workflow will refuse to publish the same version
again anyway. Prefer leaving the tag in place and cutting a new patch
version. Only delete a tag if it never triggered a successful publish and
you are re-tagging the same version on a fixed commit; delete it locally
and remotely (`git tag -d vX.Y.Z`, `git push origin :refs/tags/vX.Y.Z`) and
tell collaborators to `git fetch --prune --tags`.

## Testing the dashboard extra

The Textual dashboard is optional and must stay optional: nothing in the core
CLI may import `textual`. To exercise it:

```
pip install 'opentorus[dashboard]'
opentorus campaign dashboard CAMPAIGN-0001
```

The `campaign dashboard` command lands together with the campaign engine; on
an older build only the extra itself can be tested (`python -c "import
textual"`). Without the extra the command fails with an actionable message
naming `pip install 'opentorus[dashboard]'`. The `dev` extra includes
`textual` so the dashboard's headless tests run in CI, and both CI workflows
assert that `import opentorus.cli` leaves `textual` out of `sys.modules`
even when it is installed.

## Action pinning policy

- First-party actions (`actions/checkout`, `actions/setup-python`,
  `actions/upload-artifact`, `actions/download-artifact`,
  `actions/attest-build-provenance`) are referenced by major tag
  (`@v4`, `@v5`, `@v2`), the convention the existing `tests` and `lint`
  workflows already use.
- Third-party actions (`anchore/sbom-action`, `pypa/gh-action-pypi-publish`,
  `softprops/action-gh-release`) are pinned to a full commit SHA with the
  version as a trailing comment (`@<sha> # vX.Y.Z`). Two of them run with
  publish credentials (an OIDC token, `contents: write`); a tag can be moved
  by whoever controls the upstream repository, a commit SHA cannot.
- To bump a pinned action: look up the release you want, resolve its tag to a
  commit (`gh api repos/<owner>/<repo>/git/ref/tags/<tag>`; if the object
  type is `tag` rather than `commit`, dereference it once more with
  `gh api repos/<owner>/<repo>/git/tags/<sha>`), replace both the SHA and
  the version comment, and mention the bump in the pull request so the
  reviewer can re-resolve it. `tests/test_release_workflow.py` checks that
  every third-party `uses:` in `release.yml` is a 40-hex SHA with a version
  comment.
