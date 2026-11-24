"""Python packages of modules installed in the database go into the image.

A module installed through the Apps menu is not on the MANIFEST install list.
Before, its external Python dependencies never reached the image, and the next
build dropped them again. Now ``odoo reload`` reads the installed modules from
the project database(s) and adds them, with their dependencies, to the build
candidates. Modules that are only available in an addons path stay out.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from zodoo import module_tools

REPO_ROOT = Path(__file__).resolve().parents[4]


def _after_compose():
    """__after_compose.py is a hook file, not a package module - load by path."""
    path = REPO_ROOT / "odoo" / "__after_compose.py"
    spec = importlib.util.spec_from_file_location("after_compose_hook", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_module(root, name, depends=(), python=()):
    moddir = root / name
    moddir.mkdir(parents=True)
    (moddir / "__init__.py").write_text("")
    (moddir / "__manifest__.py").write_text(
        repr(
            {
                "name": name,
                "version": "19.0.1.0.0",
                "depends": list(depends),
                "external_dependencies": {"python": list(python)},
            }
        )
    )


def _clear_caches():
    for cache in (
        module_tools.name_cache,
        module_tools.Modules_Cache,
        module_tools.dep_tree_cache,
    ):
        cache.clear()


@pytest.fixture
def addons(tmp_path, monkeypatch):
    """One addons path:

    base; manifest_mod (MANIFEST install, needs lib_manifest);
    db_only (installed via UI, depends on db_dep, needs lib_db_only);
    db_dep (needs lib_db_dep); optional_mod (only available, needs lib_optional).
    """
    root = tmp_path / "addons"
    _write_module(root, "base")
    _write_module(root, "manifest_mod", ["base"], ["lib_manifest"])
    _write_module(root, "db_dep", ["base"], ["lib_db_dep"])
    _write_module(root, "db_only", ["db_dep"], ["lib_db_only"])
    _write_module(root, "optional_mod", ["base"], ["lib_optional"])

    manifest = {"install": ["manifest_mod"], "uninstall": []}
    monkeypatch.setattr(module_tools, "MANIFEST", lambda: manifest)
    monkeypatch.setattr(module_tools, "_get_addons_paths", lambda: [root])
    monkeypatch.setattr(module_tools, "customs_dir", lambda: tmp_path)
    monkeypatch.setattr(module_tools, "current_version", lambda: 19.0)
    monkeypatch.setattr(
        module_tools, "manifest_file_names", lambda: "__manifest__.py"
    )
    monkeypatch.setattr(
        module_tools.Modules,
        "resolve_pydeps",
        lambda self, deps, python_version: sorted(deps),
    )
    monkeypatch.chdir(tmp_path)
    _clear_caches()
    yield manifest
    _clear_caches()


def _pip(db_modules):
    mods = module_tools.Modules()
    names = {
        x if isinstance(x, str) else x.name
        for x in mods.get_all_used_modules(
            include_uninstall=True, db_modules=db_modules
        )
    }
    return mods.get_all_external_dependencies(sorted(names), (3, 12))["pip"]


def test_db_installed_module_brings_its_packages_and_its_dependencies(addons):
    pip = _pip({"db_only"})
    assert "lib_db_only" in pip
    assert "lib_db_dep" in pip  # transitive Odoo dependency
    assert "lib_manifest" in pip


def test_without_db_modules_only_manifest_packages(addons):
    assert _pip(set()) == ["lib_manifest"]


def test_optional_module_outside_the_set_brings_no_packages(addons):
    assert "lib_optional" not in _pip({"db_only"})


def test_package_list_does_not_depend_on_order(addons):
    first = _pip({"db_only", "manifest_mod"})
    _clear_caches()
    second = _pip({"manifest_mod", "db_only"})
    assert first == second


# --- reading the database -------------------------------------------------


def test_collect_unions_databases_and_reports_missing_source(addons):
    dbs = {
        "db1": {"base", "db_only"},
        "db2": {"base", "manifest_mod", "removed_module"},
    }

    def reader(dbname):
        if dbname == "db3":
            raise module_tools.DBModulesUnreadable("database does not exist")
        return dbs[dbname]

    found, missing, unreadable = module_tools.collect_build_modules_from_dbs(
        ["db1", "db2", "db3"], reader=reader
    )
    assert found == {"base", "db_only", "manifest_mod"}
    assert missing == {"removed_module": ["db2"]}
    assert unreadable == {"db3": "database does not exist"}


class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.conn.queries.append((sql, params))

    def fetchone(self):
        return (1,)

    def fetchall(self):
        return [("db_only",)]


class _FakeConn:
    def __init__(self):
        self.queries = []
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def close(self):
        self.closed = True


def test_db_query_takes_persisted_module_states(monkeypatch):
    import psycopg2

    from zodoo import odoo_config

    conn = _FakeConn()
    monkeypatch.setattr(psycopg2, "connect", lambda **kwargs: conn)
    monkeypatch.setattr(
        odoo_config,
        "get_postgres_connection_params",
        lambda: ("postgres", 5432, "odoo", "pw"),
    )
    monkeypatch.setattr(module_tools, "table_exists", lambda cr, table: True)

    assert module_tools.read_build_modules_from_db("mydb") == {"db_only"}
    sql, params = conn.queries[-1]
    assert "ir_module_module" in sql
    states = set(params[0])
    # 'to install' is only ever committed when it is persistent (Odoo rolls
    # back a failed install), so it counts; uninstalled modules do not.
    assert states == {"installed", "to upgrade", "to remove", "to install"}
    assert "uninstalled" not in states
    assert conn.closed


def test_unreachable_database_raises_unreadable(monkeypatch):
    import psycopg2

    from zodoo import odoo_config

    def connect(**kwargs):
        raise psycopg2.OperationalError("connection refused")

    monkeypatch.setattr(psycopg2, "connect", connect)
    monkeypatch.setattr(
        odoo_config,
        "get_postgres_connection_params",
        lambda: ("postgres", 5432, "odoo", "pw"),
    )
    with pytest.raises(module_tools.DBModulesUnreadable, match="refused"):
        module_tools.read_build_modules_from_db("mydb")


# --- the reload hook -------------------------------------------------------


class TestAfterComposeHook:
    def test_dbnames_default_to_dbname(self):
        hook = _after_compose()
        assert hook._get_db_build_dbnames({"DBNAME": "prod"}) == ["prod"]

    def test_dbnames_from_setting_sorted_and_unique(self):
        hook = _after_compose()
        settings = {"DBNAME": "prod", "PYTHON_DEPS_DBS": "b, a,b"}
        assert hook._get_db_build_dbnames(settings) == ["a", "b"]

    def test_lookup_can_be_switched_off(self):
        hook = _after_compose()
        settings = {"DBNAME": "prod", "PYTHON_DEPS_FROM_DB": "0"}
        assert hook._get_db_build_dbnames(settings) == []
        assert hook._get_db_build_modules(settings) == set()

    def test_unreadable_db_falls_back_with_visible_hint(
        self, monkeypatch, capsys
    ):
        hook = _after_compose()
        monkeypatch.setattr(
            module_tools,
            "collect_build_modules_from_dbs",
            lambda dbnames: (set(), {}, {"prod": "connection refused"}),
        )
        assert hook._get_db_build_modules({"DBNAME": "prod"}) == set()
        out = capsys.readouterr().out
        assert "'prod'" in out
        assert "connection refused" in out
        assert "MANIFEST" in out

    def test_missing_source_is_reported_with_module_and_db(
        self, monkeypatch, capsys
    ):
        hook = _after_compose()
        monkeypatch.setattr(
            module_tools,
            "collect_build_modules_from_dbs",
            lambda dbnames: ({"base"}, {"removed_module": ["prod"]}, {}),
        )
        assert hook._get_db_build_modules({"DBNAME": "prod"}) == {"base"}
        out = capsys.readouterr().out
        assert "'removed_module'" in out
        assert "prod" in out
        assert "source code" in out

    def test_requirements_hash_is_stable(self, tmp_path):
        hook = _after_compose()
        deps = {"pip": ["a", "b"], "deb": []}
        first, second = tmp_path / "1", tmp_path / "2"
        hook.store_sha_of_external_deps(deps, (3, 12), first)
        hook.store_sha_of_external_deps(dict(deps), (3, 12), second)
        assert first.read_text() == second.read_text()
