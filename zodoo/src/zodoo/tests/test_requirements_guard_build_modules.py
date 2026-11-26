"""The build guard resolves with the same module set as ``odoo reload``.

``odoo build`` checks requirements.hash before it builds. It used to resolve
the dependencies from the MANIFEST install list only. After a reload with
PYTHON_DEPS_EXTRA_MODULES (or with modules that are only installed in the
database) the stored hash then looked stale, the guard ran a plain
``odoo reload`` and the image was built without the packages of exactly those
modules. A pulled module with a new Python package then failed in
``odoo update``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from zodoo import lib_requirements_guard as guard

REPO_ROOT = Path(__file__).resolve().parents[4]


def _after_compose():
    path = REPO_ROOT / "odoo" / "__after_compose.py"
    spec = importlib.util.spec_from_file_location("after_compose_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Config:
    ODOO_VERSION = "19.0"
    ODOO_PYTHON_VERSION = "3.12.0"

    def __init__(self, working_dir):
        self.WORKING_DIR = working_dir


@pytest.fixture
def hook(monkeypatch, tmp_path):
    """The real reload hook; the dependency lookup returns one package per
    build module, so the hash depends on the module set."""
    hook = _after_compose()
    monkeypatch.setattr(hook, "_get_db_build_modules", lambda s: {"db_only"})
    monkeypatch.setattr(
        hook,
        "_get_extra_build_modules",
        lambda s: {
            x
            for x in str(s.get("PYTHON_DEPS_EXTRA_MODULES") or "").split(",")
            if x
        },
    )

    def fake_get_dependencies(config, globals_, python_version, **kwargs):
        mods = sorted(kwargs.get("db_modules") or ())
        return {"pip": [f"lib_{x}" for x in mods], "deb": []}

    monkeypatch.setattr(hook, "_get_dependencies", fake_get_dependencies)
    monkeypatch.setattr(guard, "_load_odoo_after_compose", lambda: hook)
    monkeypatch.setattr(guard, "_hook_globals", lambda: {})
    return hook


def _reload_hash(hook, settings):
    """The hash the reload hook would store for these settings."""
    deps = hook._get_dependencies(
        None, {}, (3, 12, 0), db_modules=hook._get_build_modules(settings)
    )
    value = "".join(str(deps[k]) for k in sorted(deps)) + str((3, 12, 0))
    return hook.get_string_hash(value)


SETTINGS = {"ODOO_VERSION": "19.0", "PYTHON_DEPS_EXTRA_MODULES": "pushed_mod"}


def test_guard_hash_matches_the_reload_with_extra_modules(hook, tmp_path):
    expected = guard.expected_requirements_hash(Config(tmp_path), SETTINGS)
    assert expected == _reload_hash(hook, SETTINGS)


def test_guard_hash_without_extra_modules_is_unchanged(hook, tmp_path):
    settings = {"ODOO_VERSION": "19.0"}
    expected = guard.expected_requirements_hash(Config(tmp_path), settings)
    assert expected == _reload_hash(hook, settings)
    assert expected != _reload_hash(hook, SETTINGS)


def test_build_keeps_a_hash_written_with_extra_modules(
    hook, tmp_path, monkeypatch
):
    """The T2 case: reload with the pulled module, then odoo build. The guard
    must not regenerate (that would drop the module)."""
    (tmp_path / "requirements.hash").write_text(_reload_hash(hook, SETTINGS))
    calls = []
    monkeypatch.setattr(
        guard.subprocess, "check_call", lambda cmd, cwd: calls.append(cmd)
    )
    monkeypatch.setattr(guard, "_dirty_generated_files", lambda c: [])
    assert guard.ensure_requirements_current(Config(tmp_path), SETTINGS) is False
    assert calls == []


@pytest.mark.parametrize(
    "settings, tail",
    [
        ({}, []),
        ({"PYTHON_DEPS_EXTRA_MODULES": " "}, []),
        (
            {"PYTHON_DEPS_EXTRA_MODULES": "a,b"},
            ["-cR", "PYTHON_DEPS_EXTRA_MODULES=a,b"],
        ),
    ],
)
def test_regeneration_keeps_extra_modules(settings, tail):
    assert guard.reload_command(settings) == [
        "odoo",
        "reload",
        "--no-gimera-apply",
    ] + tail


def test_stale_hash_regenerates_with_extra_modules(
    hook, tmp_path, monkeypatch
):
    (tmp_path / "requirements.hash").write_text("stale")
    calls = []
    monkeypatch.setattr(
        guard.subprocess, "check_call", lambda cmd, cwd: calls.append(cmd)
    )
    monkeypatch.setattr(guard, "_dirty_generated_files", lambda c: [])
    assert guard.ensure_requirements_current(Config(tmp_path), SETTINGS) is True
    assert calls == [
        [
            "odoo",
            "reload",
            "--no-gimera-apply",
            "-cR",
            "PYTHON_DEPS_EXTRA_MODULES=pushed_mod",
        ]
    ]
