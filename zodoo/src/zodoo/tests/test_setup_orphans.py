"""Tests for `odoo setup orphans` (zodoo.lib_setup_orphans).

Settings of deleted projects stay behind in ~/.odoo as settings.<project>
and run/<project>. The command must classify them without changing
anything, move only entries whose folder is really gone, and empty the
trash by age.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from click.testing import CliRunner

from zodoo import lib_setup_orphans as mod
from zodoo.click_config import Config


class FakeConfig(Config):
    """Config without project lookup, see test_lib_setup_status."""

    def __init__(self, conf_dir):
        self.__dict__.update(dirs={"user_conf_dir": conf_dir}, force=False)


def _project(conf_dir, name, customs_dir=None, run_settings=True):
    (conf_dir / f"settings.{name}").write_text("ODOO_DEMO=1\n")
    run_dir = conf_dir / "run" / name
    if run_settings:
        run_dir.mkdir(parents=True)
        lines = ["PROJECT_NAME=" + name]
        if customs_dir is not None:
            lines.append(f"HOST_CUSTOMS_DIR={customs_dir}")
        (run_dir / "settings").write_text("\n".join(lines) + "\n")
    return run_dir


def _snapshot(path):
    return sorted(str(x.relative_to(path)) for x in path.rglob("*"))


def _setup_tree(tmp_path):
    conf_dir = tmp_path / "dot_odoo"
    conf_dir.mkdir()
    work = tmp_path / "work"
    done = tmp_path / "done"
    present = work / "present-proj"
    present.mkdir(parents=True)
    # moved: the stored path is gone, a folder with the same name exists
    # in a search dir at depth 2 (<customer>/<ticket>)
    (done / "customer-a" / "moved-proj").mkdir(parents=True)

    _project(conf_dir, "present-proj", present)
    _project(conf_dir, "missing-proj", work / "missing-proj")
    _project(conf_dir, "moved-proj", work / "customer-a" / "moved-proj")
    _project(conf_dir, "unknown-norun", run_settings=False)
    _project(conf_dir, "unknown-nopath", customs_dir=None)
    return conf_dir, work, done


def _status(entries):
    return {x.name: x.status for x in entries}


def test_status_without_search_dirs(tmp_path):
    conf_dir, work, done = _setup_tree(tmp_path)
    entries = mod.collect_entries(conf_dir)
    assert _status(entries) == {
        "present-proj": "present",
        "missing-proj": "missing",
        # no search dir given: nothing is searched
        "moved-proj": "missing",
        "unknown-norun": "unknown",
        "unknown-nopath": "unknown",
    }


def test_status_moved_found_at_depth_2(tmp_path):
    conf_dir, work, done = _setup_tree(tmp_path)
    entries = mod.collect_entries(conf_dir, search_dirs=[work, done], depth=2)
    status = _status(entries)
    assert status["moved-proj"] == "moved"
    assert status["missing-proj"] == "missing"
    moved = next(x for x in entries if x.name == "moved-proj")
    assert moved.found == [done / "customer-a" / "moved-proj"]


def test_depth_limits_search(tmp_path):
    conf_dir, work, done = _setup_tree(tmp_path)
    entries = mod.collect_entries(conf_dir, search_dirs=[done], depth=1)
    assert _status(entries)["moved-proj"] == "missing"


def test_list_changes_nothing(tmp_path):
    conf_dir, work, done = _setup_tree(tmp_path)
    before = _snapshot(tmp_path)
    config = FakeConfig(conf_dir)
    result = CliRunner().invoke(
        mod.orphans, ["-s", str(work), "-s", str(done)], obj=config
    )
    assert result.exit_code == 0, result.output
    assert "missing-proj" in result.output
    assert "found: " + str(done / "customer-a" / "moved-proj") in result.output
    assert _snapshot(tmp_path) == before


def test_clean_moves_only_missing_to_trash(tmp_path):
    conf_dir, work, done = _setup_tree(tmp_path)
    config = FakeConfig(conf_dir)
    result = CliRunner().invoke(
        mod.orphans,
        ["-s", str(work), "-s", str(done), "--clean"],
        obj=config,
        input="y\n",
    )
    assert result.exit_code == 0, result.output

    assert not (conf_dir / "settings.missing-proj").exists()
    assert not (conf_dir / "run" / "missing-proj").exists()
    for name in (
        "present-proj",
        "moved-proj",
        "unknown-norun",
        "unknown-nopath",
    ):
        assert (conf_dir / f"settings.{name}").exists(), name

    trash_dirs = list((conf_dir / ".trash").iterdir())
    assert len(trash_dirs) == 1
    trash = trash_dirs[0]
    assert (trash / "settings.missing-proj").read_text() == "ODOO_DEMO=1\n"
    assert (trash / "run" / "missing-proj" / "settings").exists()


def test_clean_declined_changes_nothing(tmp_path):
    conf_dir, work, done = _setup_tree(tmp_path)
    before = _snapshot(tmp_path)
    config = FakeConfig(conf_dir)
    result = CliRunner().invoke(
        mod.orphans, ["--clean"], obj=config, input="n\n"
    )
    assert result.exit_code == 0, result.output
    assert _snapshot(tmp_path) == before


def test_purge_trash_by_age(tmp_path):
    conf_dir = tmp_path / "dot_odoo"
    trash = conf_dir / ".trash"
    old = trash / "20261001-120000"
    old_suffix = trash / "20261001-120000-1"
    young = trash / "20261120-120000"
    foreign = trash / "keep-me"
    for folder in (old, old_suffix, young, foreign):
        (folder / "run" / "x").mkdir(parents=True)

    now = datetime(2026, 11, 25, 12, 0, 0)
    folders = mod.trash_entries_older_than(conf_dir, 30, now=now)
    assert folders == [old, old_suffix]
    assert mod.purge_trash(conf_dir, folders) == []
    assert not old.exists() and not old_suffix.exists()
    assert young.exists() and foreign.exists()


def test_purge_trash_cli_asks(tmp_path):
    conf_dir = tmp_path / "dot_odoo"
    old = conf_dir / ".trash" / "20200101-000000"
    old.mkdir(parents=True)
    config = FakeConfig(conf_dir)
    result = CliRunner().invoke(
        mod.orphans, ["--purge-trash", "7"], obj=config, input="n\n"
    )
    assert result.exit_code == 0, result.output
    assert old.exists()
    result = CliRunner().invoke(
        mod.orphans, ["--purge-trash", "7"], obj=config, input="y\n"
    )
    assert result.exit_code == 0, result.output
    assert not old.exists()


def test_no_hardcoded_search_path():
    source = Path(mod.__file__).read_text()
    assert "ai/work" not in source
    assert "ai/done" not in source
