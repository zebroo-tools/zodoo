"""Tests for the Python-gated pin overrides of Odoo's requirements.txt.

Odoo 20 pins libsass==0.22.0 for every Python >= 3.11, but that sdist does
not build on Python 3.14. zodoo installs libsass 0.23.0 there. For older
Python releases the text stays unchanged, so existing base image hashes
stay the same.
"""

import importlib.util
from pathlib import Path

import pytest

from zodoo import lib_base_image as lbi

REPO_ROOT = Path(__file__).resolve().parents[4]

ODOO_20_REQS = """\
Jinja2==3.1.2 ; python_version > '3.10'
libsass==0.22.0 ; python_version >= '3.11'  # (Noble) Mostly to have a wheel package
lxml==6.0.2; python_version >= '3.14'  # (Resolute)
"""


@pytest.mark.parametrize("python_version", ["3.14.10", "3.14", (3, 14, 10)])
def test_libsass_moves_to_0_23_on_python_314(python_version):
    out = lbi.apply_framework_pin_overrides(ODOO_20_REQS, python_version)
    assert "libsass==0.23.0 ; python_version >= '3.11'" in out
    assert "libsass==0.22.0" not in out


@pytest.mark.parametrize("python_version", ["3.12.11", "3.13.13", None, ""])
def test_text_unchanged_below_314(python_version):
    assert (
        lbi.apply_framework_pin_overrides(ODOO_20_REQS, python_version)
        == ODOO_20_REQS
    )


def test_other_libsass_version_is_untouched():
    reqs = "libsass==0.22.0.post1\nlibsass==0.21.0\n"
    assert lbi.apply_framework_pin_overrides(reqs, "3.14.10") == reqs


def test_yanked_overrides_still_apply():
    out = lbi.apply_framework_pin_overrides("cbor2==5.4.2\n", "3.12.11")
    assert out == "cbor2==5.4.6\n"


def test_base_requirements_use_project_python(tmp_path, monkeypatch):
    (tmp_path / "odoo").mkdir()
    (tmp_path / "odoo" / "requirements.txt").write_text(ODOO_20_REQS)

    class Manifest(dict):
        pass

    monkeypatch.setattr("zodoo.odoo_config.MANIFEST", lambda: Manifest())

    class Config:
        WORKING_DIR = tmp_path
        ODOO_PYTHON_VERSION = "3.14.10"

    assert "libsass==0.23.0" in lbi._odoo_framework_requirements_text(Config)
    Config.ODOO_PYTHON_VERSION = "3.12.11"
    assert lbi._odoo_framework_requirements_text(Config) == ODOO_20_REQS


def _after_compose():
    path = REPO_ROOT / "odoo" / "__after_compose.py"
    spec = importlib.util.spec_from_file_location("after_compose_hook", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_project_layer_constraints_match_base():
    hook = _after_compose()
    out = hook._filter_framework_requirements(ODOO_20_REQS, (3, 14, 10))
    assert "libsass==0.23.0" in out
    assert "lxml" not in out
    out = hook._filter_framework_requirements(ODOO_20_REQS, (3, 12, 11))
    assert "libsass==0.22.0" in out
