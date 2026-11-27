"""Tests for the framework pin overrides in odoo/__after_compose.py.

Odoo 20 pins libsass==0.22.0 for every Python >= 3.11, but that sdist does
not build on Python 3.14. zodoo moves 3.14 to libsass 0.23.0 and leaves the
pin unchanged for older Python releases.
"""

import importlib.util
from pathlib import Path

import pytest
from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def hook():
    path = REPO_ROOT / "odoo" / "__after_compose.py"
    spec = importlib.util.spec_from_file_location("after_compose_hook", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ODOO_20_REQS = """\
Jinja2==3.1.2 ; python_version > '3.10'
libsass==0.22.0 ; python_version >= '3.11'  # (Noble) Mostly to have a wheel package
lxml==6.0.2; python_version >= '3.14'  # (Resolute)
"""


def _pins_for(text, python_version):
    """Package -> pinned version that pip would install for that Python."""
    pins = {}
    for line in text.splitlines():
        req = Requirement(line.split(" #")[0].strip())
        if req.marker is None or req.marker.evaluate(
            {"python_version": python_version}
        ):
            pins[req.name.lower()] = str(req.specifier)
    return pins


def test_libsass_moves_to_0_23_on_python_314(hook):
    out = hook._filter_framework_requirements(ODOO_20_REQS)
    assert _pins_for(out, "3.14")["libsass"] == "==0.23.0"


@pytest.mark.parametrize("python_version", ["3.12", "3.13"])
def test_libsass_pin_unchanged_below_314(hook, python_version):
    out = hook._filter_framework_requirements(ODOO_20_REQS)
    assert _pins_for(out, python_version)["libsass"] == "==0.22.0"


def test_other_lines_untouched_and_lxml_dropped(hook):
    out = hook._filter_framework_requirements(ODOO_20_REQS)
    assert "Jinja2==3.1.2 ; python_version > '3.10'" in out.splitlines()
    assert "lxml" not in out


def test_pin_without_marker_gets_scoped(hook):
    out = hook._filter_framework_requirements("libsass==0.22.0")
    assert _pins_for(out, "3.12")["libsass"] == "==0.22.0"
    assert _pins_for(out, "3.14")["libsass"] == "==0.23.0"


def test_pin_already_scoped_away_from_314_is_untouched(hook):
    reqs = "libsass==0.22.0 ; python_version < '3.14'"
    assert hook._filter_framework_requirements(reqs) == reqs


def test_other_libsass_version_is_untouched(hook):
    reqs = "libsass==0.23.0 ; python_version >= '3.11'"
    assert hook._filter_framework_requirements(reqs) == reqs
