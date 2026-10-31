"""Backup failure paths must preserve databases and restore the app's prior state.

Live pg_dump/pg_restore and row counts are covered by the README rehearsal.
Here a failing Docker boundary exercises recovery without risking a real database.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FAKE_DOCKER = r"""
import os
import sys
from pathlib import Path

args = sys.argv[1:]
mode = os.environ["BACKUP_TEST_MODE"]
with Path(os.environ["BACKUP_TEST_LOG"]).open("a") as log:
    log.write(repr(args) + "\n")
command = " ".join(args)
if "SELECT 1 FROM pg_database" in command:
    if mode == "existing":
        print("1")
elif args[:3] == ["compose", "ps", "--status"]:
    if mode != "stopped":
        print("app-container")
elif "pg_dump" in command:
    if mode == "dump-failure":
        print("partial archive")
        sys.exit(1)
    print("archive")
elif "pg_restore --list" in command:
    sys.stdin.buffer.read()
    print("archive table of contents")
elif "pg_restore -U" in command:
    sys.stdin.buffer.read()
    if mode == "restore-failure":
        sys.exit(1)
elif "psql -X" in command:
    sys.stdin.read()
    print("public.finding=7")
    mismatch = mode == "mismatch" and args[-1] == "medrec_restore_check"
    print("public.patient=" + ("14" if mismatch else "13"))
elif not any(word in command for word in ("createdb", "dropdb", "stop app", "start app-container")):
    raise AssertionError(f"Unexpected Docker call: {args}")
"""


@pytest.fixture
def backup(tmp_path):
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    docker = binary_dir / "docker"
    docker.write_text(f"#!{sys.executable}\n{FAKE_DOCKER}")
    docker.chmod(0o755)
    log = tmp_path / "docker.log"
    archives = tmp_path / "archives"

    def run(mode):
        result = subprocess.run(
            ["bash", "scripts/backup.sh", str(archives)],
            cwd=ROOT,
            env={
                **os.environ,
                "PATH": f"{binary_dir}{os.pathsep}{os.environ['PATH']}",
                "BACKUP_TEST_MODE": mode,
                "BACKUP_TEST_LOG": str(log),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        return result, log.read_text(), list(archives.glob("*.dump"))

    return run


def test_existing_scratch_database_is_never_dropped(backup):
    result, calls, archives = backup("existing")
    assert result.returncode != 0
    assert "already exists" in result.stderr
    assert "dropdb" not in calls and "stop', 'app" not in calls
    assert not archives


@pytest.mark.parametrize("mode", ["dump-failure", "restore-failure", "mismatch"])
def test_failed_backup_restarts_app_and_publishes_no_archive(backup, mode):
    result, calls, archives = backup(mode)
    assert result.returncode != 0
    assert "'stop', 'app'" in calls and "['start', 'app-container']" in calls
    assert ("dropdb" in calls) == (mode != "dump-failure")
    assert not archives
    assert "RESTORE VERIFIED" not in result.stdout


@pytest.mark.parametrize("mode", ["running", "stopped"])
def test_verified_backup_preserves_prior_running_state(backup, mode):
    result, calls, archives = backup(mode)
    assert result.returncode == 0, result.stderr
    assert len(archives) == 1
    assert archives[0].read_text() == "archive\n"
    assert Path(str(archives[0]) + ".counts.txt").read_text() == (
        "public.finding=7\npublic.patient=13\n"
    )
    assert "RESTORE VERIFIED: medrec_restore_check" in result.stdout
    assert "dropdb" in calls
    assert ("['start', 'app-container']" in calls) == (mode == "running")
