#!/usr/bin/env bash
# Quiesce app writes, dump app-db, and verify a scratch restore before publishing it.
# Honors Docker Compose's COMPOSE_FILE, COMPOSE_PROJECT_NAME and COMPOSE_ENV_FILES.
set -euo pipefail
umask 077

cd "$(git rev-parse --show-toplevel)"
backup_dir=${1:-backups}
mkdir -p "$backup_dir"
scratch=$(mktemp -d "$backup_dir/.backup-XXXXXX")
restore_db=medrec_restore_check
restart_app=false
created_restore_db=false
cleanup() {
    status=$?
    trap - EXIT
    if $created_restore_db; then
        docker compose exec -T app-db sh -eu -c \
            'dropdb -U "$POSTGRES_USER" medrec_restore_check' || status=1
    fi
    if $restart_app; then
        # Compose start also starts dependencies (including the one-shot seeders).
        # Restart the exact paused container without rerunning any other writer.
        docker start "$app_container" >/dev/null || status=1
    fi
    rm -rf -- "$scratch"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Refuse to delete a pre-existing database, including on a failed earlier run.
exists=$(docker compose exec -T app-db sh -eu -c \
    'psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1 -c "SELECT 1 FROM pg_database WHERE datname = '\''medrec_restore_check'\''"')
if [[ -n $exists ]]; then
    echo "medrec_restore_check already exists; inspect/remove it before retrying" >&2
    exit 1
fi
app_container=$(docker compose ps --status running -q app)
if [[ -n $app_container ]]; then
    restart_app=true
    docker compose stop app
fi

docker compose exec -T app-db sh -eu -c \
    'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner' > "$scratch/archive.dump"
test -s "$scratch/archive.dump"
docker compose exec -T app-db pg_restore --list < "$scratch/archive.dump" > "$scratch/toc.txt"
docker compose exec -T app-db sh -eu -c \
    'createdb -U "$POSTGRES_USER" -T template0 medrec_restore_check'
created_restore_db=true
docker compose exec -T app-db sh -eu -c \
    'pg_restore -U "$POSTGRES_USER" -d medrec_restore_check --no-owner --exit-on-error --single-transaction' \
    < "$scratch/archive.dump"

counts() {
    docker compose exec -T app-db sh -eu -c \
        'psql -X -U "$POSTGRES_USER" -d "${1:-$POSTGRES_DB}" -At -v ON_ERROR_STOP=1' sh "$1" <<'SQL'
SELECT table_schema || '.' || table_name || '=' ||
       (xpath('/row/n/text()', query_to_xml(
           format('SELECT count(*) AS n FROM %I.%I', table_schema, table_name),
           false, true, '')))[1]::text
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name;
SQL
}
counts '' > "$scratch/source-counts.txt"
counts "$restore_db" > "$scratch/restored-counts.txt"
test -s "$scratch/source-counts.txt"
diff -u "$scratch/source-counts.txt" "$scratch/restored-counts.txt"

archive="$backup_dir/medrec-$(date -u +%Y%m%dT%H%M%SZ)-${scratch##*-}.dump"
mv "$scratch/archive.dump" "$archive"
cp "$scratch/source-counts.txt" "$archive.counts.txt"
printf 'RESTORE VERIFIED: %s\n' "$restore_db"
cat "$archive.counts.txt"
printf 'Verified archive: %s\n' "$archive"
