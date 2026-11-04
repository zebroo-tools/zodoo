"""Locale cleanup in `odoo/config/common.docker` (zodoo issue #274).

The final cleanup used to delete every locale dir except `en_US`, so
`locale.setlocale(LC_COLLATE, "de_DE.UTF-8")` at import time broke the
registry and `odoo update` for all modules. locales-all also links files
across locale dirs (de_DE.utf8/LC_COLLATE -> ../aa_DJ.utf8/LC_COLLATE), so
keeping a dir by name alone still leaves dangling links. Bases without
locales-all (Odoo 17+) only ship en_US, so missing locales are generated.

The test runs the shell fragment from common.docker against a fake
/usr/lib/locale tree, with stand-ins for `locale` and `localedef`.
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


@pytest.fixture
def fake_bin(tmp_path, locale_dir):
    """`locale -a` lists the fake tree; `localedef` logs its call and knows
    every locale except xx_YY."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "localedef.log"
    (bin_dir / "locale").write_text(f'#!/bin/sh\nls "{locale_dir}"\n')
    (bin_dir / "localedef").write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> "{log}"\n'
        'case "$*" in *xx_YY*) exit 4;; esac\n'
    )
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    return bin_dir, log


def _run(locale_dir, keep, cwd, fake_bin, check=True):
    bin_dir, _log = fake_bin
    env = dict(
        os.environ,
        ODOO_KEEP_LOCALES=keep,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
    )
    proc = subprocess.run(
        ["sh", "-c", _locale_fragment(locale_dir)],
        env=env,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )
    if not check:
        return proc
    return sorted(p.name for p in locale_dir.iterdir())


def test_keeps_configured_locales_without_dangling_links(
    locale_dir, tmp_path, fake_bin
):
    # A file in cwd matching a pattern must not be picked up by the shell glob.
    (tmp_path / "x_de_DE_x").write_text("")
    left = _run(locale_dir, "de_DE", cwd=tmp_path, fake_bin=fake_bin)
    assert left == ["de_DE.utf8", "en_US.utf8", "locale-archive"]
    for name in ("de_DE.utf8", "en_US.utf8"):
        collate = locale_dir / name / "LC_COLLATE"
        assert not collate.is_symlink()
        assert collate.read_text() == "aa_DJ.utf8 collate"
        assert (locale_dir / name / "LC_PAPER").read_text() == "C.utf8 collate"

    # Present locales are kept as they are, nothing is generated.
    assert not fake_bin[1].exists()


def test_en_us_is_always_kept(locale_dir, tmp_path, fake_bin):
    left = _run(locale_dir, "", cwd=tmp_path, fake_bin=fake_bin)
    assert left == ["en_US.utf8", "locale-archive"]


def test_several_locales(locale_dir, tmp_path, fake_bin):
    left = _run(locale_dir, "de_DE fr_FR", cwd=tmp_path, fake_bin=fake_bin)
    assert left == ["de_DE.utf8", "en_US.utf8", "fr_FR.utf8", "locale-archive"]


def test_missing_locale_is_generated(locale_dir, tmp_path, fake_bin):
    _run(locale_dir, "de_DE it_IT", cwd=tmp_path, fake_bin=fake_bin)
    assert fake_bin[1].read_text().splitlines() == [
        "-i it_IT -c -f UTF-8 it_IT.UTF-8"
    ]


def test_unknown_locale_fails_the_build(locale_dir, tmp_path, fake_bin):
    proc = _run(
        locale_dir, "xx_YY", cwd=tmp_path, fake_bin=fake_bin, check=False
    )
    assert proc.returncode != 0
    assert "cannot generate locale xx_YY" in proc.stderr
    # Nothing was deleted before the failure.
    assert (locale_dir / "fr_FR.utf8").is_dir()
