"""The host job queue (lib_jobqueue) behind background registry uploads.

Two failures seen on a build server:

- The detached worker was started as a bare ``odoo run-crontab`` in the
  project directory. Projects driven through ``-xs``/``-p`` (a wrapper with
  its own settings file, or a checkout in a temporary directory whose name
  differs from the project) then either resolved another project and
  reported "processed 0 job(s)", or aborted on the directory name check.
  Their queues filled up for months.
- A failed job was renamed to ``.failed.<n>`` and never looked at again, so
  one 401 from the registry lost the upload for good.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from zodoo import lib_jobqueue


def _config(tmp_path, max_attempts=3, delay_minutes=10, max_age_hours=24):
    return SimpleNamespace(
        dirs={"run": tmp_path},
        WORKING_DIR=tmp_path,
        project_name="proj1",
        restrict={},
        ZODOO_JOBQUEUE_MAX_ATTEMPTS_as_int=max_attempts,
        ZODOO_JOBQUEUE_RETRY_DELAY_MINUTES_as_int=delay_minutes,
        ZODOO_JOBQUEUE_RETRY_MAX_AGE_HOURS_as_int=max_age_hours,
    )


def _failed_job(
    qdir, n, created_ago=timedelta(hours=1), failed_ago=3600, body=None
):
    qdir.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc) - created_ago
    job = {
        "id": "job1",
        "type": "registry_upload",
        "payload": {},
        "created_at": created.isoformat(),
    }
    job.update(body or {})
    path = qdir / f"job1.json.failed.{n}"
    path.write_text(json.dumps(job))
    mtime = time.time() - failed_ago
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def handler(monkeypatch):
    calls = []

    def run(config, payload):
        calls.append(payload)
        if run.fail:
            raise RuntimeError("401 Unauthorized")

    run.fail = False
    monkeypatch.setattr(
        lib_jobqueue, "_get_handlers", lambda: {"registry_upload": run}
    )
    run.calls = calls
    return run


# ---------------------------------------------------------------- worker


def test_worker_gets_project_and_restrict_files(tmp_path):
    config = _config(tmp_path)
    config.restrict = {
        "settings": [Path("/home/u/.cicd/settings")],
        "docker-compose": [Path("/home/u/.cicd/docker-compose.yml")],
    }
    assert lib_jobqueue._worker_command(config) == [
        "odoo",
        "-xs",
        "/home/u/.cicd/settings",
        "-xd",
        "/home/u/.cicd/docker-compose.yml",
        "-p",
        "proj1",
        "run-crontab",
    ]


def test_spawn_worker_passes_project(tmp_path, monkeypatch):
    seen = {}

    def popen(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["cwd"] = kwargs["cwd"]

    monkeypatch.setattr(lib_jobqueue.subprocess, "Popen", popen)
    lib_jobqueue.spawn_worker(_config(tmp_path))
    assert seen["cmd"] == ["odoo", "-p", "proj1", "run-crontab"]
    assert seen["cwd"] == str(tmp_path)


# ----------------------------------------------------------------- retry


def test_failure_counts_attempts(tmp_path, handler):
    config = _config(tmp_path)
    lib_jobqueue.enqueue(config, "registry_upload", {"image": "x"})
    handler.fail = True
    lib_jobqueue.process_pending(config)
    (failed,) = (tmp_path / "jobqueue").glob("*.failed.*")
    assert failed.name.endswith(".failed.1")
    assert json.loads(failed.read_text())["attempts"] == 1


def test_failed_job_is_retried_and_succeeds(tmp_path, handler):
    config = _config(tmp_path)
    qdir = tmp_path / "jobqueue"
    _failed_job(qdir, 1, body={"attempts": 1})
    assert lib_jobqueue.process_pending(config) == 1
    assert len(handler.calls) == 1
    assert not list(qdir.glob("job1*"))


def test_retry_stops_at_max_attempts(tmp_path, handler):
    config = _config(tmp_path, max_attempts=3, delay_minutes=0)
    lib_jobqueue.enqueue(config, "registry_upload", {})
    handler.fail = True
    for _ in range(5):
        lib_jobqueue.process_pending(config)
    assert len(handler.calls) == 3
    (failed,) = (tmp_path / "jobqueue").glob("*.failed.*")
    assert failed.name.endswith(".failed.3")


def test_no_retry_before_delay(tmp_path, handler):
    config = _config(tmp_path, delay_minutes=10)
    _failed_job(tmp_path / "jobqueue", 1, failed_ago=60)
    assert lib_jobqueue.process_pending(config) == 0
    assert not handler.calls


def test_no_retry_for_old_jobs(tmp_path, handler):
    """Old jobs may point at images or registries that are gone; pushing
    them again on every build would only burn bandwidth."""
    config = _config(tmp_path, max_age_hours=24)
    _failed_job(tmp_path / "jobqueue", 1, created_ago=timedelta(days=30))
    assert lib_jobqueue.process_pending(config) == 0
    assert not handler.calls


def test_legacy_failed_name_counts_as_attempts(tmp_path, handler):
    """Jobs from before the counter carry it only in the file name."""
    config = _config(tmp_path, max_attempts=3)
    _failed_job(tmp_path / "jobqueue", 3)
    assert lib_jobqueue.process_pending(config) == 0
    assert not handler.calls


def test_retry_off_when_setting_missing(tmp_path, handler):
    config = _config(tmp_path, max_attempts=None)
    _failed_job(tmp_path / "jobqueue", 1, body={"attempts": 1})
    assert lib_jobqueue.process_pending(config) == 0
    assert not handler.calls
