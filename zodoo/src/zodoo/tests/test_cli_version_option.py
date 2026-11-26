# Part of Zebroo GmbH. See LICENSE file for full copyright and licensing details (www.zebroo.de/license).
"""Tests for the top-level `odoo --version` option.

The option must print the same version as `odoo version` (one source:
`_get_version()`), exit with rc 0 and must not run the root group callback,
so it works outside a project directory (e.g. `ssh host 'odoo --version'`).
"""

from click.testing import CliRunner

from zodoo import cli
from zodoo.tools import _get_version


def test_version_option_prints_version_and_exits_zero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = CliRunner().invoke(cli, ["--version"])
    assert res.exit_code == 0, res.output
    assert res.output.strip() == _get_version()


def test_version_option_skips_project_setup(tmp_path, monkeypatch):
    """The root callback resolves the project; --version must not reach it."""
    monkeypatch.chdir(tmp_path)

    def _fail(*args, **kwargs):
        raise AssertionError("project setup must not run for --version")

    import zodoo.tools

    monkeypatch.setattr(zodoo.tools, "_get_default_project_name", _fail)
    monkeypatch.setattr(zodoo.tools, "_project_name_from_settings", _fail)
    res = CliRunner().invoke(cli, ["--version"])
    assert res.exit_code == 0, res.output
    assert res.output.strip() == _get_version()
