# Publishing a release

Run commands from the repository root after the changes have been reviewed and
the `lint` and `test` checks pass. Publishing requires GitHub CLI (`gh`); building
requires Bash, Docker, uv and Python 3.12.

## Prepare the version

Update the version in `pyproject.toml`, refresh `uv.lock` with `uv lock`, and add
the release's changes to [CHANGELOG](../CHANGELOG.md) and `docs/releases/`.
The project version, changelog entry and Git tag must agree.

## Build and verify

For version 1.1.0, after the preparation PR is approved, CI passes and it is merged:

```sh
git switch main
git pull --ff-only
git tag -a v1.1.0 -m "MedRec 1.1.0"
scripts/build_release.sh 1.1.0
scripts/build_release.sh 1.0.0
```

The build script accepts lightweight or annotated tags, resolves the full tag
reference to a commit, and builds a detached checkout of that commit. It labels
the image with its version and commit, and rejects a version mismatch or an
existing image tagged with a different revision. The published lightweight
`v1.0.0` is valid and must not be replaced or moved.

Follow the [operations guide](OPERATIONS.md) to start the image in a disposable
Compose project and verify a backup restore. Record the results alongside the
release notes and README before publishing. Run the complete same-volume
1.1.0 → 1.0.0 → 1.1.0 demonstration: verified backups before switching,
health/version and running-container revision checks, newer history with
`Other (frequency_mismatch)` and summaries under 1.0.0, a successful new 1.0.0
run, and full labels restored under 1.1.0. The current branch prepares that
procedure; do not claim final tagged-image evidence before the tag exists.

## Publish

```sh
git push origin v1.1.0
gh release create v1.1.0 --verify-tag --title "MedRec 1.1.0" --notes-file docs/releases/1.1.0.md
```

Published tags are immutable. Make fixes in a new version rather than moving a
published tag.
