"""`odoo update` in a baked image (no .git) when nothing is due.

Baked images drop .git, so the incremental update falls back to MANIFEST
mode. For a project whose MANIFEST installs nothing beyond base and has no
outdated module, that fallback used to end in ``Exception("no modules to
update")`` - every pod started with UPDATE_ON_STARTUP=1 exited with 255
(bake test ``test_bake_flow[19.0]`` since 03.11.2026).
"""

from types import SimpleNamespace

import pytest

from zodoo import lib_module
from zodoo import module_tools


def _call(tmp_path, monkeypatch, manifest_mode=False):
    monkeypatch.chdir(tmp_path)  # no .git here, like /opt/src in a baked image
    monkeypatch.setattr(lib_module, "_get_setting", lambda conn, key: "abc123")
    monkeypatch.setattr(lib_module, "_get_default_modules_to_update", lambda *a: [])
    monkeypatch.setattr(
        module_tools.DBModules,
        "check_if_all_modules_from_install_are_installed",
        staticmethod(lambda check_func=None: []),
    )
    config = SimpleNamespace(get_odoo_conn=lambda: None)
    opts = SimpleNamespace(no_restart=True, no_dangling_check=True)
    return lib_module._perform_install(
        module=(),
        config=config,
        ctx=None,
        opts=opts,
        manifest={"uninstall": []},
        update_log_file=None,
        since_git_sha=None,
        manifest_mode=manifest_mode,
        installed_modules=False,
        dangling_modules=False,
        no_outdated_modules=False,
        update_strategy=None,
        param_module=None,
    )


def test_baked_image_nothing_due_exits_cleanly(tmp_path, monkeypatch, capsys):
    assert _call(tmp_path, monkeypatch) is None
    out = capsys.readouterr().out
    assert "Falling back to full MANIFEST update" in out
    assert "No module update required" in out


def test_explicit_manifest_mode_still_raises(tmp_path, monkeypatch):
    # `odoo update -M` with an empty MANIFEST stays an error - only the
    # automatic SHA fallback is relaxed.
    with pytest.raises(Exception, match="no modules to update"):
        _call(tmp_path, monkeypatch, manifest_mode=True)


def test_ci_project_name(monkeypatch):
    from .conftest import ci_project_name

    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    assert ci_project_name("zodoo_pytest_pgbackrest", "zptpgbr") == (
        "zodoo_pytest_pgbackrest"
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "43773646509")
    name = ci_project_name("zodoo_pytest_pgbackrest", "zptpgbr")
    assert name == "zptpgbr46509"
    # Socket path budget on the runners (see ci_project_name).
    assert len(name) <= 23
