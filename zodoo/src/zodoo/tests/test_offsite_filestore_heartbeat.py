"""Every successful filestore run must leave a manifest line on the receiver.

The backup server measures "time since the last successful run" as the age of
the newest manifest. A run with nothing new used to upload nothing at all, so a
quiet instance aged into the "no backup for 48 h" alarm although every run was
fine. These tests drive offsite/filestore-wo.sh directly in bash, with the
network helpers replaced by functions that record what would be sent - no
Docker, no receiver.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

OFFSITE = Path(__file__).resolve().parents[4] / "offsite"


def _gnu_userland() -> bool:
    """filestore-wo.sh uses GNU find -printf and stat -c (it runs in Debian)."""
    if not shutil.which("bash"):
        return False
    res = subprocess.run(
        ["find", ".", "-maxdepth", "0", "-printf", ""], capture_output=True
    )
    return res.returncode == 0


pytestmark = pytest.mark.skipif(
    not _gnu_userland(), reason="needs bash and GNU find (Linux)"
)

# Sourced after the real scripts, so these replace the network helpers.
_STUBS = r"""
wo_append_manifest() {
    [ -z "${FAIL_MANIFEST:-}" ] || return 22
    printf '%s\t%s\n' "$2" "$3" >> "$CALLS/manifests"
}
# Records the upload instead of streaming it: the real command needs `age`,
# which the test machine does not have to provide.
wo_put_stream() {
    local name="$1"
    [ -z "${FAIL_UPLOAD:-}" ] || return 1
    echo "$name" >> "$CALLS/objects"
    echo "$name 0000000000000000000000000000000000000000000000000000000000000000 42"
}
wo_filestore_root() { echo "$FILESTORE"; }
"""


def _run(tmp_path: Path, **env) -> subprocess.CompletedProcess:
    script = (
        f". '{OFFSITE}/wo-common.sh'\n"
        f". '{OFFSITE}/filestore-wo.sh'\n"
        f"{_STUBS}\n"
        "do_filestore || exit 7\n"
    )
    base_env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "OFFSITE_STATE_DIR": str(tmp_path / "state"),
        "OFFSITE_WO_URL": "https://receiver.invalid/area/",
        "OFFSITE_WO_RECIPIENT": "age1dummy",
        "OFFSITE_REST_USER": "area",
        "OFFSITE_REST_PASSWORD": "x",
        "CA_CERT": str(tmp_path / "no-ca.crt"),
        "DBNAME": "db",
        "PROJECT_NAME": "proj",
        "FILESTORE": str(tmp_path / "filestore"),
        "CALLS": str(tmp_path / "calls"),
    }
    base_env.update(env)
    return subprocess.run(
        ["bash", "-c", script], env=base_env, capture_output=True, text=True
    )


def _manifests(tmp_path: Path) -> list[dict]:
    path = tmp_path / "calls" / "manifests"
    if not path.exists():
        return []
    return [
        json.loads(line.split("\t", 1)[1])
        for line in path.read_text().splitlines()
        if line
    ]


@pytest.fixture
def setup(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "calls").mkdir()
    fs = tmp_path / "filestore" / "ab"
    fs.mkdir(parents=True)
    (fs / "abcdef").write_bytes(b"attachment")
    return tmp_path


def test_nothing_new_still_declares_the_run(setup):
    first = _run(setup)
    assert first.returncode == 0, first.stderr
    assert len(_manifests(setup)) == 1
    assert _manifests(setup)[0]["bundle"]

    second = _run(setup)
    assert second.returncode == 0, second.stderr
    assert "nothing new" in second.stdout
    lines = _manifests(setup)
    assert (
        len(lines) == 2
    ), "a run with nothing new left no trace on the receiver"
    beat = lines[1]
    assert beat["kind"] == "filestore"
    assert beat["files_added"] == 0
    assert beat["files_total"] == 1
    # No object was uploaded, so the line must not name one: wo-check would
    # otherwise report it as declared but missing.
    assert "bundle" not in beat
    assert (setup / "calls" / "objects").read_text().count("\n") == 1


def test_failed_declaration_fails_the_run(setup):
    assert _run(setup).returncode == 0
    res = _run(setup, FAIL_MANIFEST="1")
    # The run must not count as successful when the receiver never saw it:
    # do_backup collects the failure through the return value.
    assert res.returncode == 7, (res.stdout, res.stderr)
    assert len(_manifests(setup)) == 1


def _ledger(tmp_path: Path) -> str:
    path = tmp_path / "state" / "filestore.ledger"
    return path.read_text() if path.exists() else ""


def test_failed_upload_fails_the_run_and_keeps_the_ledger(setup):
    res = _run(setup, FAIL_UPLOAD="1")
    assert res.returncode == 7, (res.stdout, res.stderr)
    # Nothing arrived, so nothing may count as uploaded - otherwise these
    # files are never offered again.
    assert _ledger(setup) == ""
    assert _manifests(setup) == []


def test_bundle_is_declared_before_a_heartbeat_can_follow(setup):
    """Upload ok, manifest POST failed, then a retry.

    The bundle was never declared. If the ledger already listed its files, the
    retry would find nothing new and send a fresh heartbeat for a backup the
    receiver cannot account for.
    """
    res = _run(setup, FAIL_MANIFEST="1")
    assert res.returncode == 7, (res.stdout, res.stderr)
    assert _ledger(setup) == ""
    assert _manifests(setup) == []

    retry = _run(setup)
    assert retry.returncode == 0, retry.stderr
    lines = _manifests(setup)
    assert len(lines) == 1, lines
    assert lines[0][
        "bundle"
    ], "the retry sent a heartbeat instead of the bundle"
    assert lines[0]["files_added"] == 1
    assert "ab/abcdef" in _ledger(setup)


def test_empty_filestore_is_not_a_successful_run(setup):
    # An empty filestore is what an unmounted volume looks like.
    (setup / "filestore" / "ab" / "abcdef").unlink()
    res = _run(setup)
    assert res.returncode == 7, (res.stdout, res.stderr)
    assert _manifests(setup) == []
