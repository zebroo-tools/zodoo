"""The dev copy keeps "Base: Auto-vacuum internal data" running.

Up to Odoo 15 turndb2dev.sql switched off every cron, including
base.autovacuum_job - bus_bus, sessions and the like then grow without limit
in restored instances (one CI database reached 44 GB of bus_bus). From 16 on
Odoo's own neutralize.sql already spares that cron; 9.0-15 now do the same.

The cron also runs the filestore GC, which is only safe on a filestore
directory of the database's own. A symlink into the shared pool switches it
off again.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from zodoo import lib_turnintodev as mod

CONFIG_DIR = Path(mod.__file__).parents[3] / "odoo" / "config"

KEEP_AUTOVACUUM = (
    "update ir_cron set active=false where id not in (select res_id from "
    "ir_model_data where model = 'ir.cron' and module = 'base' and name = "
    "'autovacuum_job');"
)


@pytest.mark.parametrize("version", ["9.0", "11", "12", "13", "14", "15"])
def test_turndb2dev_spares_autovacuum_cron(version):
    lines = (CONFIG_DIR / version / "turndb2dev.sql").read_text().splitlines()

    cron_lines = [line for line in lines if "ir_cron" in line]
    assert cron_lines == [KEEP_AUTOVACUUM]
    # the line-by-line runner executes each line on its own
    assert KEEP_AUTOVACUUM in lines


@pytest.fixture
def executed(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mod, "_execute_sql", lambda conn, sql, **kw: calls.append(sql)
    )
    return calls


def _config(tmp_path, dbname="odoo"):
    (tmp_path / "filestore").mkdir(exist_ok=True)
    return SimpleNamespace(ODOO_FILES=str(tmp_path), dbname=dbname)


def test_own_filestore_keeps_autovacuum(tmp_path, executed):
    config = _config(tmp_path)
    (tmp_path / "filestore" / "odoo" / "checklist").mkdir(parents=True)

    mod._keep_gc_off_on_shared_filestore(config, conn=None)

    assert executed == []


def test_no_filestore_yet_keeps_autovacuum(tmp_path, executed):
    mod._keep_gc_off_on_shared_filestore(_config(tmp_path), conn=None)

    assert executed == []


def test_without_odoo_files_nothing_happens(executed):
    config = SimpleNamespace(ODOO_FILES=None, dbname="odoo")

    mod._keep_gc_off_on_shared_filestore(config, conn=None)

    assert executed == []


def test_symlinked_filestore_switches_autovacuum_off(tmp_path, executed):
    config = _config(tmp_path)
    common = tmp_path / "filestore" / "_common"
    (common / "checklist").mkdir(parents=True)
    (tmp_path / "filestore" / "odoo").symlink_to(common)

    mod._keep_gc_off_on_shared_filestore(config, conn=None)

    assert executed == [mod.DISABLE_AUTOVACUUM_SQL]
    assert "autovacuum_job" in mod.DISABLE_AUTOVACUUM_SQL


def test_symlinked_checklist_switches_autovacuum_off(tmp_path, executed):
    config = _config(tmp_path)
    shared = tmp_path / "shared_checklist"
    shared.mkdir()
    db_dir = tmp_path / "filestore" / "odoo"
    db_dir.mkdir()
    (db_dir / "checklist").symlink_to(shared)

    mod._keep_gc_off_on_shared_filestore(config, conn=None)

    assert executed == [mod.DISABLE_AUTOVACUUM_SQL]


def test_turn_into_devdb_runs_the_guard(tmp_path, monkeypatch, executed):
    from zodoo import odoo_config

    sql_dir = tmp_path / "images" / "odoo" / "config" / "15"
    sql_dir.mkdir(parents=True)
    (sql_dir / "turndb2dev.sql").write_text("")
    settings = tmp_path / "settings"
    settings.write_text("")

    config = _config(tmp_path)
    config.dirs = {"images": tmp_path / "images"}
    config.files = {"settings": settings}
    config.proxy_port = 80
    (tmp_path / "filestore" / "odoo").symlink_to(tmp_path)

    monkeypatch.setattr(odoo_config, "current_version", lambda: 15.0)
    monkeypatch.setattr(mod, "_run_odoo_neutralize", lambda *a, **k: None)
    monkeypatch.setattr(mod, "__collect_other_turndb2dev_sql", lambda: [])
    monkeypatch.setattr(mod, "_update_setting", lambda **kw: None)

    getattr(mod, "__turn_into_devdb")(None, config, conn=None)

    assert mod.DISABLE_AUTOVACUUM_SQL in executed
