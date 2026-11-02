#!/usr/bin/env bash
# Roll the running 1.0.0 app forward to the 1.1.0 image on the same database volume.
# Run this after scripts/rollback.sh. scripts/backup.sh stops the app, verifies the
# dump, then resumes that container. This script then exports APP_VERSION=1.1.0 and
# starts that image with docker compose.
# Honors Docker Compose's COMPOSE_FILE, COMPOSE_PROJECT_NAME and COMPOSE_ENV_FILES.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

from_version=1.0.0
to_version=1.1.0
port=${APP_PORT:-8000}
health_url="http://127.0.0.1:${port}/healthz"

health_body() {
    curl --fail --silent --show-error "$health_url"
}

if ! docker image inspect "medrec-app:$to_version" >/dev/null 2>&1; then
    echo "medrec-app:$to_version is missing; build it with scripts/build_release.sh $to_version" >&2
    exit 1
fi

container=$(docker compose ps --status running -q app)
if [[ -z $container ]]; then
    echo "app is not running; start $from_version before rolling forward" >&2
    exit 1
fi

running_version=$(docker inspect "$container" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')
if [[ $running_version != "$from_version" ]]; then
    echo "running app image version is ${running_version:-unset}, expected $from_version" >&2
    exit 1
fi

expected_from="{\"status\":\"ok\",\"version\":\"$from_version\"}"
actual_from=$(health_body)
if [[ $actual_from != "$expected_from" ]]; then
    echo "expected $health_url to report $expected_from, got: $actual_from" >&2
    exit 1
fi

scripts/backup.sh

export APP_VERSION=$to_version
docker compose up -d --no-build --no-deps --wait app

deadline=$((SECONDS + 60))
expected_to="{\"status\":\"ok\",\"version\":\"$to_version\"}"
actual_to=""
until actual_to=$(health_body) && [[ $actual_to == "$expected_to" ]]; do
    if ((SECONDS >= deadline)); then
        echo "roll-forward failed: expected $expected_to, got: ${actual_to:-no response}" >&2
        exit 1
    fi
    sleep 1
done

rolled_container=$(docker compose ps --status running -q app)
rolled_version=$(docker inspect "$rolled_container" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')
if [[ $rolled_version != "$to_version" ]]; then
    echo "app came up as ${rolled_version:-unset}, expected $to_version" >&2
    exit 1
fi

printf 'ROLLED FORWARD: %s -> %s\n' "$from_version" "$to_version"
printf '%s\n' "$actual_to"
