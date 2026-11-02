#!/usr/bin/env bash
# Build an immutable release image from its Git tag
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
version=${1:?Usage: scripts/build_release.sh VERSION (for example 1.0.0)}
if [[ ! $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Expected a release version such as 1.0.0" >&2
    exit 1
fi
tag="v$version"
if ! revision=$(git rev-parse --verify "refs/tags/$tag^{commit}" 2>/dev/null); then
    echo "$tag must exist and point to a commit (lightweight or annotated)" >&2
    exit 1
fi
image="medrec-app:$version"
if docker image inspect "$image" >/dev/null 2>&1; then
    existing=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")
    if [[ $existing != "$revision" ]]; then
        echo "Refusing to overwrite $image: revision $existing differs from $revision" >&2
        exit 1
    fi
fi

scratch=$(mktemp -d "${TMPDIR:-/tmp}/medrec-release.XXXXXX")
cleanup() {
    status=$?
    trap - EXIT
    if [[ -d $scratch/source ]]; then
        git worktree remove --force "$scratch/source" || status=1
    fi
    rmdir "$scratch" || status=1
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
git worktree add --detach "$scratch/source" "$revision"

# uv is already required for local development; tomllib reads the actual tag's version.
actual=$(uv run --no-project --python 3.12 python -c \
    'import pathlib, sys, tomllib; print(tomllib.loads(pathlib.Path(sys.argv[1]).read_text())["project"]["version"])' \
    "$scratch/source/pyproject.toml")
if [[ $actual != "$version" ]]; then
    echo "$tag contains project version $actual, expected $version" >&2
    exit 1
fi
docker build --file "$scratch/source/infra/Dockerfile" \
    --build-arg "VCS_REF=$revision" \
    --label "org.opencontainers.image.version=$version" \
    --tag "$image" "$scratch/source"
[[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image") == "$revision" ]]
[[ $(docker run --rm --entrypoint python "$image" -c 'from app.version import __version__; print(__version__)') == "$version" ]]
printf 'RELEASE IMAGE VERIFIED: %s\nrevision=%s\n' "$image" "$revision"
