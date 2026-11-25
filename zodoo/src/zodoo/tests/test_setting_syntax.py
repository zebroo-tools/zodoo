"""`odoo setting` without "=" must not silently do nothing.

Without "=" every argument is a key to look up, so `odoo setting ODOO_DEMO 1`
used to read two keys, write nothing and print nothing. Arguments that cannot
be a key name now stop with the corrected command; a key that is not set is
reported instead of printing nothing.
"""

import pytest
from click.testing import CliRunner

from zodoo import lib_composer
from zodoo.myconfigparser import MyConfigParser
from zodoo.tests.test_lib_control import FakeConfig


@pytest.fixture
def settings_file(tmp_path):
    path = tmp_path / "settings"
    path.write_text("PROXY_PORT=8069\nODOO_DEMO=0\nDEVMODE=1\n")
    return path


def _invoke(settings_file, *args):
    cfg = FakeConfig(
        files={"settings": settings_file, "project_settings": settings_file}
    )
    return CliRunner().invoke(lib_composer.setting, list(args), obj=cfg)


def _content(settings_file):
    parser = MyConfigParser(settings_file)
    return {k: parser[k] for k in parser.keys()}


@pytest.mark.parametrize(
    "args",
    [
        ("ODOO_DEMO", "1"),
        ("ODOO_DEMO", "true"),
        ("ODOO_DEMO", "No"),
        ("ODOO_DEMO", "/tmp/x"),
        ("ODOO_DEMO", "a-b"),
        ("1",),
        ("yes",),
        ("./settings",),
        ("PROXY_PORT", "ODOO_DEMO", "1"),
    ],
)
def test_value_without_equals_aborts(settings_file, args):
    before = settings_file.read_text()
    res = _invoke(settings_file, *args)
    assert res.exit_code != 0, res.output
    assert "Meintest du" in res.output
    assert "odoo setting " in res.output and "=" in res.output
    assert settings_file.read_text() == before


def test_key_value_pair_suggests_correct_form(settings_file):
    res = _invoke(settings_file, "ODOO_DEMO", "1")
    assert res.exit_code != 0
    assert "odoo setting ODOO_DEMO=1" in res.output
    assert _content(settings_file)["ODOO_DEMO"] == "0"


def test_write_with_equals_unchanged(settings_file):
    res = _invoke(settings_file, "-R", "ODOO_DEMO=1")
    assert res.exit_code == 0, res.output
    assert "ODOO_DEMO=1" in res.output
    assert _content(settings_file)["ODOO_DEMO"] == "1"


def test_read_key_unchanged(settings_file):
    res = _invoke(settings_file, "PROXY_PORT")
    assert res.exit_code == 0, res.output
    assert res.output.strip() == "PROXY_PORT=8069"


def test_read_several_keys(settings_file):
    res = _invoke(settings_file, "PROXY_PORT", "DEVMODE")
    assert res.exit_code == 0, res.output
    assert res.output.split() == ["DEVMODE=1", "PROXY_PORT=8069"]


def test_read_lowercase_partial_name(settings_file):
    res = _invoke(settings_file, "port")
    assert res.exit_code == 0, res.output
    assert res.output.strip() == "PROXY_PORT=8069"


def test_read_missing_key_says_not_set(settings_file):
    res = _invoke(settings_file, "DOES_NOT_EXIST")
    assert res.exit_code == 0, res.output
    assert res.output.strip() == "DOES_NOT_EXIST: nicht gesetzt"


def test_read_mixed_found_and_missing(settings_file):
    res = _invoke(settings_file, "PROXY_PORT", "_UNKNOWN")
    assert res.exit_code == 0, res.output
    assert "PROXY_PORT=8069" in res.output
    assert "_UNKNOWN: nicht gesetzt" in res.output
