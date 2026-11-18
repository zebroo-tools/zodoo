"""A module name that exists in more than one addons path must resolve to the
copy in the FIRST addons path - the same rule Odoo applies
(odoo.modules.module.get_module_path).

Real case: ``password_security`` existed in a project addons path (needs
zxcvbn) and in OCA/server-auth further down (no zxcvbn). zodoo picked the OCA
copy, so zxcvbn was missing in requirements.txt and the module update failed.
"""

from __future__ import annotations

import pytest

from zodoo import module_tools


def _write_module(root, name, external_dependencies):
    moddir = root / name
    moddir.mkdir(parents=True)
    (moddir / "__init__.py").write_text("")
    (moddir / "__manifest__.py").write_text(
        repr(
            {
                "name": name,
                "version": "17.0.1.0.0",
                "depends": [],
                "external_dependencies": external_dependencies,
            }
        )
    )


@pytest.fixture
def two_addons_paths(tmp_path, monkeypatch):
    first = tmp_path / "addons" / "addons-intero"
    second = tmp_path / "addons_OCA" / "server-auth"
    _write_module(first, "password_security", {"python": ["zxcvbn"]})
    _write_module(second, "password_security", {"python": []})
    # A module that exists only in the second path is still found.
    _write_module(second, "auth_only_oca", {"python": ["oca_only_lib"]})

    monkeypatch.setattr(module_tools, "_get_addons_paths", lambda: [first, second])
    monkeypatch.setattr(module_tools, "customs_dir", lambda: tmp_path)
    monkeypatch.setattr(module_tools, "current_version", lambda: 17.0)
    monkeypatch.setattr(
        module_tools, "manifest_file_names", lambda: "__manifest__.py"
    )
    monkeypatch.chdir(tmp_path)
    for cache in (
        module_tools.name_cache,
        module_tools.Modules_Cache,
        module_tools.dep_tree_cache,
    ):
        cache.clear()
    yield tmp_path, first
    for cache in (
        module_tools.name_cache,
        module_tools.Modules_Cache,
        module_tools.dep_tree_cache,
    ):
        cache.clear()


def test_get_modules_first_addons_path_wins(two_addons_paths):
    root, first = two_addons_paths
    modules = module_tools.Modules._get_modules(no_deptree=True)

    mod = modules["password_security"]
    assert (root / mod.path).resolve() == (first / "password_security").resolve()
    assert mod.manifest_dict["external_dependencies"] == {"python": ["zxcvbn"]}
    assert "auth_only_oca" in modules


def test_get_by_name_first_addons_path_wins(two_addons_paths):
    root, first = two_addons_paths
    mod = module_tools.Module.get_by_name("password_security")

    assert mod.manifest_dict["external_dependencies"] == {"python": ["zxcvbn"]}
    assert (root / mod.path).resolve() == (first / "password_security").resolve()


def test_external_dependencies_come_from_first_addons_path(
    two_addons_paths, monkeypatch
):
    # resolve_pydeps talks to pip/markers; only the collected names matter here.
    monkeypatch.setattr(
        module_tools.Modules,
        "resolve_pydeps",
        lambda self, deps, python_version: sorted(deps),
    )
    deps = module_tools.Modules().get_all_external_dependencies(
        ["password_security", "auth_only_oca"], (3, 11)
    )
    assert deps["pip"] == ["oca_only_lib", "zxcvbn"]
