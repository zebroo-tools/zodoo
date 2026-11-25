"""Make the pipx bin dir (and with it the `odoo` command) reachable for
non-interactive shells such as `ssh host 'odoo ...'`.

`pipx ensurepath` appends its PATH line to the end of ~/.bashrc. The
Ubuntu/Debian default ~/.bashrc returns early for non-interactive shells
("If not running interactively, don't do anything"), so that line is never
reached when sshd runs a command. bash still sources ~/.bashrc in that case,
so a block at the very top of the file works.

The block is written idempotently and is the only place zodoo touches
~/.bashrc. Other lines (e.g. the ones pipx appended) are left alone.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

BEGIN_MARKER = "# >>> zodoo PATH >>>"
END_MARKER = "# <<< zodoo PATH <<<"


def pipx_bin_dir() -> Path:
    """Directory where pipx puts the `odoo` entry point."""
    try:
        value = subprocess.check_output(
            ["pipx", "environment", "--value", "PIPX_BIN_DIR"],
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        value = ""
    return Path(value) if value else Path.home() / ".local" / "bin"


def _shell_path(bin_dir: Path, home: Path) -> str:
    # Keep the block portable across users: write $HOME instead of the
    # absolute home path when possible.
    try:
        return "$HOME/" + str(bin_dir.relative_to(home))
    except ValueError:
        return str(bin_dir)


def render_block(bin_dir: Path, home: Path) -> str:
    path = _shell_path(bin_dir, home)
    return (
        f"{BEGIN_MARKER}\n"
        "# Managed by zodoo (install.sh / odoo setup reinstall). Must stay\n"
        "# above the interactive guard so `ssh host 'odoo ...'` finds odoo.\n"
        f'case ":$PATH:" in *":{path}:"*) ;; *) export PATH="{path}:$PATH" ;; esac\n'
        f"{END_MARKER}\n"
    )


def _strip_block(text: str) -> str:
    lines = text.splitlines(keepends=True)
    result = []
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped == BEGIN_MARKER:
            inside = True
            continue
        if inside:
            if stripped == END_MARKER:
                inside = False
            continue
        result.append(line)
    if inside:
        # Unterminated block: do not guess what belongs to it.
        return text
    return "".join(result)


def ensure_bashrc_path(bashrc: Path, bin_dir: Path, home: Path) -> bool:
    """Put the zodoo PATH block at the top of `bashrc`.

    Returns True if the file was changed. A second call with the same
    arguments returns False and does not touch the file.
    """
    block = render_block(bin_dir, home)
    current = bashrc.read_text() if bashrc.exists() else ""
    if current.startswith(block):
        return False
    rest = _strip_block(current)
    if BEGIN_MARKER in rest:
        raise RuntimeError(
            f"{bashrc} contains an unterminated '{BEGIN_MARKER}' block; "
            "please fix it by hand."
        )
    new = block + ("\n" + rest.lstrip("\n") if rest.strip() else "")
    # Write through symlinks and keep the file mode.
    with open(bashrc, "w") as fh:
        fh.write(new)
    return True


def ensure_path_for_non_interactive_shells() -> bool:
    home = Path(os.path.expanduser("~"))
    return ensure_bashrc_path(home / ".bashrc", pipx_bin_dir(), home)
