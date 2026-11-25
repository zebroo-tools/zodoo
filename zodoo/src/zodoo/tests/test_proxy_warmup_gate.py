"""Host side of the proxy warmup gate (`_touch_proxy_warmup_gate`).

The odoo container runs as root and creates the sentinel itself when the
web role respawns. A later `odoo update` on the host (non-root user) then
failed with "[warmup gate] could not touch ...: Permission denied", because
touch() needs write access to the existing file. Without root the test
cannot create a root-owned file, so it imitates one: a read-only file makes
the open() in touch() fail, and os.utime() fails like it does for a file of
another user.
"""

import os
import stat
from types import SimpleNamespace

import pytest

from zodoo.lib_control_with_docker import _touch_proxy_warmup_gate


def _config(tmp_path):
    return SimpleNamespace(dirs={"run": tmp_path})


def _sentinel(tmp_path):
    return tmp_path / "proxy_exchange" / "warmup_in_progress"


def test_creates_sentinel_readable_for_proxy(tmp_path, capsys):
    _touch_proxy_warmup_gate(_config(tmp_path))

    p = _sentinel(tmp_path)
    assert p.exists()
    # The proxy's nginx workers run as nobody and open the file for reading.
    assert stat.S_IMODE(p.stat().st_mode) == 0o644
    assert "could not touch" not in capsys.readouterr().out


@pytest.mark.skipif(
    os.geteuid() == 0, reason="root can write a read-only file anyway"
)
def test_sentinel_not_writable_by_host_user(tmp_path, capsys, monkeypatch):
    def utime_foreign_file(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "utime", utime_foreign_file)
    p = _sentinel(tmp_path)
    p.parent.mkdir(parents=True)
    p.parent.chmod(0o777)
    p.write_text("")
    p.chmod(0o444)
    with pytest.raises(PermissionError):
        p.touch()

    _touch_proxy_warmup_gate(_config(tmp_path))

    assert "could not touch" not in capsys.readouterr().out
    assert p.exists()
    assert stat.S_IMODE(p.stat().st_mode) == 0o644
