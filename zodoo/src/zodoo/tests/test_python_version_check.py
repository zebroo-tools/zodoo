"""Tests for the Odoo x Python version check in lib_composer.

The supported range comes from MIN_PY_VERSION/MAX_PY_VERSION in the
project's odoo/release.py. zodoo aborts with a clear message when
ODOO_PYTHON_VERSION is outside that range.
"""

from __future__ import annotations

from unittest import mock

import pytest

from zodoo import lib_composer as mod

RELEASE_19 = """
version_info = (19, 0, 0, 'final', 0, '')
MIN_PY_VERSION = (3, 10)
MAX_PY_VERSION = (3, 14)
MIN_PG_VERSION = 13
"""

RELEASE_19_OLD = """
MIN_PY_VERSION = (3, 10)
MAX_PY_VERSION = (3, 13)
"""

RELEASE_20 = """
MIN_PY_VERSION = (3, 12)
MAX_PY_VERSION = (3, 14)
"""

RELEASE_NO_CONSTANTS = """
version_info = (16, 0, 0, 'final', 0, '')
"""


@pytest.fixture
def release(tmp_path):
    def _make(content):
        path = tmp_path / "release.py"
        path.write_text(content)
        return path

    return _make


@pytest.fixture
def secho():
    with mock.patch("zodoo.tools.click.secho") as patched:
        yield patched


def _check(python_version, odoo_version, release_file):
    mod._check_python_version_supported(
        python_version, odoo_version, release_file=release_file
    )


def test_read_range_from_release_file(release):
    assert mod._read_odoo_python_range(release(RELEASE_20)) == (
        (3, 12),
        (3, 14),
    )


def test_read_range_without_constants(release):
    assert mod._read_odoo_python_range(release(RELEASE_NO_CONSTANTS)) == (
        None,
        None,
    )


def test_read_range_missing_file(tmp_path):
    assert mod._read_odoo_python_range(tmp_path / "nope.py") is None


@pytest.mark.parametrize("version", ["3.12.11", "3.13.13", "3.14.2", "3.10.0"])
def test_supported_versions_pass_on_odoo_19(release, secho, version):
    _check(version, "19", release(RELEASE_19))
    secho.assert_not_called()


def test_python_314_on_old_odoo_19_checkout_aborts(release, secho):
    with pytest.raises(SystemExit):
        _check("3.14.2", "19", release(RELEASE_19_OLD))
    message = secho.call_args[0][0]
    assert "3.14" in message
    assert "3.10 to 3.13" in message
    assert "ODOO_PYTHON_VERSION" in message


def test_python_311_on_odoo_20_aborts(release, secho):
    with pytest.raises(SystemExit):
        _check("3.11.10", "20", release(RELEASE_20))
    message = secho.call_args[0][0]
    assert "too old" in message
    assert "3.12" in message


def test_python_315_on_odoo_20_aborts(release, secho):
    with pytest.raises(SystemExit):
        _check("3.15.0", "20", release(RELEASE_20))


def test_fallback_minimum_for_odoo_17_without_constants(release, secho):
    with pytest.raises(SystemExit):
        _check("3.9.17", "17", release(RELEASE_NO_CONSTANTS))


def test_old_odoo_without_constants_is_not_checked(release, secho):
    _check("3.9.17", "16", release(RELEASE_NO_CONSTANTS))
    secho.assert_not_called()


def test_unparsable_version_is_ignored(release, secho):
    _check("", "19", release(RELEASE_19))
    _check(None, "19", release(RELEASE_19))
    secho.assert_not_called()


def test_missing_release_file_on_odoo_19_warns(tmp_path, secho):
    _check("3.14.10", "19", tmp_path / "missing" / "release.py")
    assert secho.call_count == 1
    assert "Could not read the Python range" in secho.call_args[0][0]


def test_missing_release_file_on_odoo_20_still_checks_minimum(tmp_path, secho):
    with pytest.raises(SystemExit):
        _check("3.9.17", "20", tmp_path / "missing" / "release.py")
