# Part of Zebroo GmbH. See LICENSE file for full copyright and licensing details (www.zebroo.de/license).
"""Unit tests for the output directories of the robot image runner.

Fast, no Docker: robot/robotest.py runs inside the robot image, so its
third-party imports (robot, dotenv, arrow) are stubbed here.
"""

import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[4]
ROBOTEST = REPO_ROOT / "robot" / "robotest.py"


def _load_robotest():
    stubs = {
        "robot": types.SimpleNamespace(rebot=mock.Mock(), run=mock.Mock()),
        "dotenv": types.SimpleNamespace(load_dotenv=mock.Mock()),
        "arrow": types.SimpleNamespace(utcnow=mock.Mock()),
    }
    with mock.patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("robotest", ROBOTEST)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def test_unique_stem_keeps_short_name():
    robotest = _load_robotest()
    src = Path("/opt/src")
    files = [
        src / "tests/suites/a/test_a.robot",
        src / "mod/tests/test_b.robot",
    ]
    names = robotest._output_sub_dir_names(files, 1)
    assert names == {files[0]: "test_a_p1", files[1]: "test_b_p1"}


def test_same_stem_gets_distinct_dirs():
    robotest = _load_robotest()
    src = Path("/opt/src")
    files = [
        src / "tests/suites/test_mapper/test_mapper.robot",
        src / "zbsync_odoo_mapper/tests/test_mapper.robot",
    ]
    names = robotest._output_sub_dir_names(files, 2)
    assert names[files[0]] == "tests__suites__test_mapper__test_mapper_p2"
    assert names[files[1]] == "zbsync_odoo_mapper__tests__test_mapper_p2"


def test_run_tests_writes_same_stem_suites_apart(tmp_path):
    """Both suites run, each into its own directory; none is skipped."""
    robotest = _load_robotest()
    src = Path("/opt/src")
    files = [
        src / "tests/suites/test_mapper/test_mapper.robot",
        src / "zbsync_odoo_mapper/tests/test_mapper.robot",
    ]
    seen = []

    def fake_run_test(test_file, output_dir, **params):
        seen.append(output_dir)
        return {"all_ok": True}

    with mock.patch.object(
        robotest, "_run_test", side_effect=fake_run_test
    ), mock.patch.object(robotest, "collect_all_reports"):
        results = robotest._run_tests({"parallel": 1}, iter(files), tmp_path)

    assert len(results) == 2
    assert len(set(seen)) == 2
    assert all(path.is_dir() for path in seen)
