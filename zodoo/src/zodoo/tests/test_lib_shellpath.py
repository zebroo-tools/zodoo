"""Tests for zodoo.lib_shellpath (PATH block at the top of ~/.bashrc).

sshd runs `ssh host 'cmd'` through a non-interactive bash that sources
~/.bashrc. The Ubuntu default ~/.bashrc returns early in that case, so the
line `pipx ensurepath` appends at the end is never reached. BASH_ENV makes a
plain `bash -c` source the file in the same non-interactive mode, which is
what these tests use to simulate the ssh case.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from zodoo import lib_shellpath as mod

SKEL = Path(__file__).parent / "data" / "ubuntu-24.04-skel.bashrc"
PIPX_ENSUREPATH_LINE = (
    "\n# Created by `pipx` on 2026-01-01 00:00:00\n"
    'export PATH="$PATH:$HOME/.local/bin"\n'
)

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash not available"
)


@pytest.fixture
def home(tmp_path):
    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    odoo = bin_dir / "odoo"
    odoo.write_text("#!/bin/sh\necho zodoo-test\n")
    odoo.chmod(0o755)
    bashrc = tmp_path / ".bashrc"
    bashrc.write_text(SKEL.read_text() + PIPX_ENSUREPATH_LINE)
    return tmp_path


def _command_v_odoo(home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", "command -v odoo"],
        env={
            "HOME": str(home),
            "PATH": "/usr/bin:/bin",
            "BASH_ENV": str(home / ".bashrc"),
        },
        capture_output=True,
        text=True,
    )


def test_without_block_odoo_is_not_found(home):
    # Baseline: what a host looks like today. Proves the next test would
    # fail without ensure_bashrc_path().
    assert _command_v_odoo(home).returncode != 0


def test_block_makes_odoo_reachable_non_interactively(home):
    assert mod.ensure_bashrc_path(
        home / ".bashrc", home / ".local" / "bin", home
    )
    res = _command_v_odoo(home)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == str(home / ".local" / "bin" / "odoo")


def test_block_is_at_the_top_and_uses_home_variable(home):
    mod.ensure_bashrc_path(home / ".bashrc", home / ".local" / "bin", home)
    text = (home / ".bashrc").read_text()
    assert text.startswith(mod.BEGIN_MARKER + "\n")
    assert '"$HOME/.local/bin:$PATH"' in text
    assert str(home) not in text
    # The rest of the original file is kept unchanged.
    assert text.endswith(SKEL.read_text() + PIPX_ENSUREPATH_LINE)


def test_second_run_changes_nothing(home):
    bashrc = home / ".bashrc"
    assert mod.ensure_bashrc_path(bashrc, home / ".local" / "bin", home)
    first = bashrc.read_text()
    assert not mod.ensure_bashrc_path(bashrc, home / ".local" / "bin", home)
    assert bashrc.read_text() == first
    assert first.count(mod.BEGIN_MARKER) == 1


def test_block_not_at_top_is_moved(home):
    bashrc = home / ".bashrc"
    block = mod.render_block(home / ".local" / "bin", home)
    bashrc.write_text(SKEL.read_text() + "\n" + block)
    assert mod.ensure_bashrc_path(bashrc, home / ".local" / "bin", home)
    text = bashrc.read_text()
    assert text.startswith(block)
    assert text.count(mod.BEGIN_MARKER) == 1
    assert _command_v_odoo(home).returncode == 0


def test_path_not_duplicated_when_already_set(home):
    mod.ensure_bashrc_path(home / ".bashrc", home / ".local" / "bin", home)
    bin_dir = str(home / ".local" / "bin")
    res = subprocess.run(
        ["bash", "-c", 'printf "%s" "$PATH"'],
        env={
            "HOME": str(home),
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "BASH_ENV": str(home / ".bashrc"),
        },
        capture_output=True,
        text=True,
    )
    assert res.stdout.split(":").count(bin_dir) == 1


def test_missing_bashrc_is_created(tmp_path):
    bashrc = tmp_path / ".bashrc"
    assert mod.ensure_bashrc_path(
        bashrc, tmp_path / ".local" / "bin", tmp_path
    )
    assert bashrc.read_text() == mod.render_block(
        tmp_path / ".local" / "bin", tmp_path
    )


def test_bin_dir_outside_home_is_written_absolute(tmp_path):
    bashrc = tmp_path / ".bashrc"
    mod.ensure_bashrc_path(bashrc, Path("/opt/pipx/bin"), tmp_path)
    assert '"/opt/pipx/bin:$PATH"' in bashrc.read_text()


def test_unterminated_block_is_refused(home):
    bashrc = home / ".bashrc"
    broken = mod.BEGIN_MARKER + "\nexport PATH=x\n" + SKEL.read_text()
    bashrc.write_text(broken)
    with pytest.raises(RuntimeError):
        mod.ensure_bashrc_path(bashrc, home / ".local" / "bin", home)
    assert bashrc.read_text() == broken
