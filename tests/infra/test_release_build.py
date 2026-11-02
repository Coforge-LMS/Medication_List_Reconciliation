"""Exercise tag selection and release guards in a disposable Git repository."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FAKE_DOCKER = r"""
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
state = Path(os.environ["RELEASE_TEST_STATE"])
if args[:2] == ["image", "inspect"]:
    if not state.exists():
        sys.exit(1)
    if "--format" in args:
        print(json.loads(state.read_text())["revision"])
elif args[0] == "build":
    import tomllib
    source = Path(args[-1])
    revision = args[args.index("--build-arg") + 1].split("=", 1)[1]
    state.write_text(json.dumps({
        "revision": revision,
        "version": tomllib.loads((source / "pyproject.toml").read_text())["project"]["version"],
    }))
elif args[0] == "run":
    print(json.loads(state.read_text())["version"])
else:
    raise AssertionError(args)
"""


@pytest.fixture
def release_repo(tmp_path):
    checkout = tmp_path / "repo"
    checkout.mkdir()

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=checkout, text=True).strip()

    git("init", "--quiet")
    git("config", "user.name", "Release Test")
    git("config", "user.email", "release-test@example.invalid")
    (checkout / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/build_release.sh", checkout / "scripts")
    (checkout / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')
    git("add", ".")
    git("commit", "--quiet", "-m", "release source")
    revision = git("rev-parse", "HEAD")
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    for name, body in (
        ("docker", FAKE_DOCKER),
        (
            "uv",
            "import os, sys\n"
            "os.execv(sys.executable, [sys.executable, *sys.argv[sys.argv.index('-c'):]])\n",
        ),
    ):
        executable = binary_dir / name
        executable.write_text(f"#!{sys.executable}\n{body}")
        executable.chmod(0o755)
    state = tmp_path / "image.json"

    def build(version="1.0.0"):
        return subprocess.run(
            ["bash", "scripts/build_release.sh", version],
            cwd=checkout,
            env={
                **os.environ,
                "PATH": f"{binary_dir}{os.pathsep}{os.environ['PATH']}",
                "TMPDIR": str(tmp_path),
                "RELEASE_TEST_STATE": str(state),
            },
            capture_output=True,
            text=True,
            check=False,
        )

    return checkout, git, revision, state, build


@pytest.mark.parametrize("annotated", [False, True])
def test_builds_tagged_commit_even_with_a_dirty_checkout(release_repo, annotated):
    """The image comes from the tag, not HEAD, a same-named branch or uncommitted edits."""
    checkout, git, revision, state, build = release_repo
    git("tag", *(["-a", "-m", "Release 1.0.0"] if annotated else []), "v1.0.0")
    # A later commit with a same-named branch, then uncommitted edits: none is the tag.
    (checkout / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n')
    git("commit", "--quiet", "-am", "after the release")
    git("branch", "v1.0.0")
    (checkout / "pyproject.toml").write_text('[project]\nversion = "8.8.8"\n')
    result = build()
    assert result.returncode == 0, result.stderr
    assert f"revision={revision}" in result.stdout
    image = json.loads(state.read_text())
    assert image == {"revision": revision, "version": "1.0.0"}
    assert len(git("worktree", "list", "--porcelain").split("worktree ")) == 2


@pytest.mark.parametrize(
    ("tag_kind", "version", "message"),
    [
        ("missing", "1.0.0", "v1.0.0 must exist and point to a commit"),
        ("blob", "1.0.0", "v1.0.0 must exist and point to a commit"),
        ("wrong-version", "1.1.0", "v1.1.0 contains project version 1.0.0, expected 1.1.0"),
    ],
)
def test_rejects_invalid_release_before_building(release_repo, tag_kind, version, message):
    """Each bad tag fails with its own reason, before anything is built."""
    _, git, _, state, build = release_repo
    if tag_kind == "blob":
        git("tag", "v1.0.0", git("rev-parse", "HEAD:pyproject.toml"))
    elif tag_kind == "wrong-version":
        git("tag", "v1.1.0")
    result = build(version)
    assert result.returncode != 0
    assert not state.exists()
    assert message in result.stderr


def test_existing_image_cannot_be_overwritten_with_another_revision(release_repo):
    _, git, _, state, build = release_repo
    git("tag", "v1.0.0")
    state.write_text('{"revision": "another-commit", "version": "1.0.0"}')
    result = build()
    assert result.returncode != 0
    assert "Refusing to overwrite medrec-app:1.0.0" in result.stderr
    assert "another-commit" in state.read_text()
