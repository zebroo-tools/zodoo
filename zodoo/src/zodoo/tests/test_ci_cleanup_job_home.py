# Part of Zebroo GmbH. See LICENSE file for full copyright and licensing details (www.zebroo.de/license).
"""CI helper .github/scripts/cleanup-job-home.sh.

Background: on the self-hosted runners the postgres containers write socket
and log directories into the per-job HOME as a remapped UID. The runner user
cannot delete them, so every bake job left its ``_temp/h.*`` behind until the
runner disk was full (30.10.2026). The script removes exactly the job's own
home, falling back to a throwaway container for files it cannot delete.

Docker is replaced by a fake on PATH: it logs its calls and, for ``run``,
makes the mounted directory writable again and empties it - the same effect
the real container has on remapped files.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[4]
    / ".github"
    / "scripts"
    / "cleanup-job-home.sh"
)

FAKE_DOCKER = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_DOCKER_LOG"
case "$1" in
  info) exit "${FAKE_DOCKER_INFO_RC:-0}" ;;
  ps) for id in ${FAKE_DOCKER_PS:-}; do echo "$id"; done; exit 0 ;;
  inspect)
    id="${!#}"
    [[ -f "${FAKE_DOCKER_MOUNTS:-}" ]] || exit 0
    while IFS='|' read -r cid rest; do
      [[ "$cid" == "$id" ]] && echo "$rest"
    done < "$FAKE_DOCKER_MOUNTS"
    exit 0 ;;
  run)
    for arg in "$@"; do
      case "$arg" in *:/job-home) src="${arg%:/job-home}" ;; esac
    done
    [[ "${FAKE_DOCKER_RUN_NOOP:-}" == 1 ]] && exit 0
    chmod -R u+rwx "$src"
    find "$src" -mindepth 1 -delete
    ;;
esac
exit 0
"""

pytestmark = [
    pytest.mark.skipif(
        not SCRIPT.exists() or shutil.which("bash") is None,
        reason="cleanup script or bash not available",
    ),
    # root can delete the "locked" directories, so the fallback paths
    # would not be exercised.
    pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="must not run as root",
    ),
]


@pytest.fixture
def env(tmp_path):
    runner_temp = tmp_path / "_temp"
    runner_temp.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    log = tmp_path / "docker.log"
    log.touch()
    environ = dict(os.environ)
    environ.update(
        RUNNER_TEMP=str(runner_temp),
        PATH=f"{bindir}{os.pathsep}{environ.get('PATH', '')}",
        FAKE_DOCKER_LOG=str(log),
    )
    return runner_temp, environ, log


def _run(path, environ):
    return subprocess.run(
        ["bash", str(SCRIPT), str(path)],
        env=environ,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _locked_home(runner_temp, name="h.abc123"):
    """A job home with a directory the current user cannot empty."""
    home = runner_temp / name
    locked = home / ".odoo" / "run" / "baketest190" / "postgres.socket"
    locked.mkdir(parents=True)
    (locked / ".s.PGSQL.5432.lock").write_text("x")
    locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    return home, locked


def _unlock(path):
    if path.exists():
        path.chmod(stat.S_IRWXU)


def test_removes_plain_job_home(env):
    runner_temp, environ, log = env
    home = runner_temp / "h.XYZ123"
    (home / "pipx" / "venvs").mkdir(parents=True)
    (home / ".odoo").mkdir()
    (home / ".odoo" / "settings").write_text("SECRET=1")
    keep = runner_temp / "bake-logs"
    keep.mkdir()

    res = _run(home, environ)

    assert res.returncode == 0, res.stdout + res.stderr
    assert not home.exists()
    assert keep.exists(), "artifacts next to the job home must stay"
    assert " run " not in f" {log.read_text()}"


def test_missing_home_is_no_error(env):
    runner_temp, environ, _ = env
    res = _run(runner_temp / "h.gone00", environ)
    assert res.returncode == 0
    assert "nothing to do" in res.stdout


@pytest.mark.parametrize(
    "make_path",
    [
        lambda t: t.parent / "h.outside",  # not below RUNNER_TEMP
        lambda t: t / "tools-home.abc",  # wrong prefix
        lambda t: t / "h.abc" / "h.nested",  # not directly below
        lambda t: t,  # RUNNER_TEMP itself
    ],
)
def test_refuses_foreign_paths(env, make_path):
    runner_temp, environ, _ = env
    target = make_path(runner_temp)
    target.mkdir(parents=True, exist_ok=True)
    marker = target / "marker"
    marker.write_text("x")

    res = _run(target, environ)

    assert res.returncode == 2, res.stdout + res.stderr
    assert "::error::" in res.stdout
    assert marker.exists()


def test_refuses_symlink(env, tmp_path):
    runner_temp, environ, _ = env
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "data").write_text("x")
    link = runner_temp / "h.link00"
    link.symlink_to(victim)

    res = _run(link, environ)

    assert res.returncode == 2
    assert (victim / "data").exists()


def test_refuses_without_runner_temp(env):
    runner_temp, environ, _ = env
    home = runner_temp / "h.abc123"
    home.mkdir()
    del environ["RUNNER_TEMP"]
    res = _run(home, environ)
    assert res.returncode == 2
    assert home.exists()


def test_undeletable_files_go_through_docker(env):
    runner_temp, environ, log = env
    home, locked = _locked_home(runner_temp)
    try:
        res = _run(home, environ)
    finally:
        _unlock(locked)

    assert res.returncode == 0, res.stdout + res.stderr
    assert not home.exists()
    calls = log.read_text()
    assert f"{home.resolve()}:/job-home" in calls
    assert "--network none" in calls


def test_only_containers_of_this_home_are_removed(env, tmp_path):
    """The tools runners share one daemon and bake uses fixed project names:
    a parallel bake (same project, other home) must survive."""
    runner_temp, environ, log = env
    home, locked = _locked_home(runner_temp)
    other = (runner_temp / "h.abc123x").resolve()  # prefix of ours + "x"
    sock = home.resolve() / ".odoo" / "run" / "baketest190" / "postgres.socket"
    mounts = tmp_path / "mounts"
    mounts.write_text(
        f"own1|bind|{sock}|\n"
        "own1|volume|/var/lib/docker/volumes/v1/_data|baketest190_pgdata\n"
        f"par1|bind|{other}/.odoo/run/baketest190/postgres.socket|\n"
        "par1|volume|/var/lib/docker/volumes/v2/_data|baketest190_other\n"
        "unrel|bind|/srv/something|\n"
    )
    environ["FAKE_DOCKER_PS"] = "own1 par1 unrel"
    environ["FAKE_DOCKER_MOUNTS"] = str(mounts)
    try:
        res = _run(home, environ)
    finally:
        _unlock(locked)

    assert res.returncode == 0, res.stdout + res.stderr
    removals = [l for l in log.read_text().splitlines() if l.startswith("rm ")]
    assert removals == ["rm -f own1"]
    assert "volume rm baketest190_pgdata" in log.read_text()
    assert "baketest190_other" not in "".join(
        l for l in log.read_text().splitlines() if l.startswith("volume")
    )


def test_leftovers_are_a_warning_not_a_failure(env):
    runner_temp, environ, _ = env
    home, locked = _locked_home(runner_temp)
    environ["FAKE_DOCKER_RUN_NOOP"] = "1"
    try:
        res = _run(home, environ)
        assert res.returncode == 0, res.stdout + res.stderr
        assert "::warning::" in res.stdout
        assert home.exists()
    finally:
        _unlock(locked)


def test_without_docker_leftovers_are_a_warning(env):
    runner_temp, environ, log = env
    home, locked = _locked_home(runner_temp)
    environ["FAKE_DOCKER_INFO_RC"] = "1"
    try:
        res = _run(home, environ)
        assert res.returncode == 0
        assert "::warning::" in res.stdout
        assert " run " not in f" {log.read_text()}"
    finally:
        _unlock(locked)
