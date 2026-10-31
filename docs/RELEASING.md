# Publishing a release

Run commands from the repository root after the changes have been reviewed and
the `lint` and `test` checks pass. Publishing requires GitHub CLI (`gh`); building
requires Bash, Docker, uv and Python 3.12.

## Prepare the version

Update the version in `pyproject.toml`, refresh `uv.lock` with `uv lock`, and add
the release's changes to [CHANGELOG](../CHANGELOG.md) and `docs/releases/`.
The project version, changelog entry and Git tag must agree.

## Build and verify

For version 1.0.0:

```sh
git switch main
git pull --ff-only
git tag -a v1.0.0 -m "MedRec 1.0.0"
scripts/build_release.sh 1.0.0
```

The build script uses a detached checkout of the annotated tag and labels the
image with its version and commit. It rejects a version mismatch or an existing
image tagged with a different revision.

Follow the [operations guide](OPERATIONS.md) to start the image in a disposable
Compose project and verify a backup restore. Record the results alongside the
release notes before publishing.

## Publish

```sh
git push origin v1.0.0
gh release create v1.0.0 --verify-tag --title "MedRec 1.0.0" --notes-file docs/releases/1.0.0.md
```

Published tags are immutable. Make fixes in a new version rather than moving a
published tag.
