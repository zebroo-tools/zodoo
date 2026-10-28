"""Locale cleanup in `odoo/config/common.docker` (zodoo issue #274).

The final cleanup used to delete every locale dir except `en_US`, so
`locale.setlocale(LC_COLLATE, "de_DE.UTF-8")` at import time broke the
registry and `odoo update` for all modules. locales-all also links files
across locale dirs (de_DE.utf8/LC_COLLATE -> ../aa_DJ.utf8/LC_COLLATE), so
keeping a dir by name alone still leaves dangling links.

The test runs the shell fragment from common.docker against a fake
/usr/lib/locale tree.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
COMMON_DOCKER = REPO_ROOT / "odoo" / "config" / "common.docker"


def _locale_fragment(locale_dir):
    text = COMMON_DOCKER.read_text()
    m = re.search(
        r"^    set -- && \\\n.*?-exec rm -rf \{\} \+ \|\| true && \\\n",
        text,
        re.M | re.S,
    )
    assert m, "locale cleanup fragment not found in common.docker"
    fragment = m.group(0).rstrip().removesuffix("&& \\").rstrip()
    return fragment.replace("/usr/lib/locale", str(locale_dir))


@pytest.fixture
def locale_dir(tmp_path):
    root = tmp_path / "locale"
    for name in ("aa_DJ.utf8", "de_AT.utf8", "C.utf8", "fr_FR.utf8"):
        (root / name).mkdir(parents=True)
        (root / name / "LC_COLLATE").write_text(f"{name} collate")
    for name in ("de_DE.utf8", "en_US.utf8"):
        (root / name).mkdir()
        (root / name / "LC_COLLATE").symlink_to("../aa_DJ.utf8/LC_COLLATE")
        (root / name / "LC_PAPER").symlink_to("../C.utf8/LC_COLLATE")
    (root / "locale-archive").write_text("archive")
    return root


def _run(locale_dir, keep, cwd):
    env = dict(os.environ, ODOO_KEEP_LOCALES=keep)
    subprocess.run(
        ["sh", "-c", _locale_fragment(locale_dir)],
        env=env,
        cwd=cwd,
        check=True,
    )
    return sorted(p.name for p in locale_dir.iterdir())


def test_keeps_configured_locales_without_dangling_links(locale_dir, tmp_path):
    # A file in cwd matching a pattern must not be picked up by the shell glob.
    (tmp_path / "x_de_DE_x").write_text("")
    left = _run(locale_dir, "de_DE", cwd=tmp_path)
    assert left == ["de_DE.utf8", "en_US.utf8", "locale-archive"]
    for name in ("de_DE.utf8", "en_US.utf8"):
        collate = locale_dir / name / "LC_COLLATE"
        assert not collate.is_symlink()
        assert collate.read_text() == "aa_DJ.utf8 collate"
        assert (locale_dir / name / "LC_PAPER").read_text() == "C.utf8 collate"


def test_en_us_is_always_kept(locale_dir, tmp_path):
    left = _run(locale_dir, "", cwd=tmp_path)
    assert left == ["en_US.utf8", "locale-archive"]


def test_several_locales(locale_dir, tmp_path):
    left = _run(locale_dir, "de_DE fr_FR", cwd=tmp_path)
    assert left == ["de_DE.utf8", "en_US.utf8", "fr_FR.utf8", "locale-archive"]
