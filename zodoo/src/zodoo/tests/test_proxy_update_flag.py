"""Host side of the proxy update flag (`proxy_exchange/odoo_update`).

`odoo update` writes "1" into the flag before the update and "0" when it
ends. The bundled proxy polls the file every second, serves the maintenance
page (HTTP 503) while it says "1", and deletes it after reading. Its nginx
workers run as `nobody`, so the file must be readable for other users.
atomic_write_text() creates it via mkstemp with mode 0600 unless a mode is
passed -- then the proxy cannot open it and the maintenance page never shows.
"""

import inspect
import stat
from types import SimpleNamespace

import pytest

from zodoo import lib_module


class _StopUpdate(Exception):
    pass


class _Config:
    """Minimal config: the update aborts at the first real step.

    Reading `odoo_version` is the first thing `update` does after setting
    the flag, so the property records the flag as the proxy would see it
    during the update and then stops the run.
    """

    DEVMODE = False

    def __init__(self, run_dir):
        self.dirs = {"run": run_dir}
        self.flag = run_dir / "proxy_exchange" / "odoo_update"
        self.seen_during_update = None

    @property
    def odoo_version(self):
        self.seen_during_update = (
            self.flag.read_text(),
            stat.S_IMODE(self.flag.stat().st_mode),
        )
        raise _StopUpdate()


def _run_update(config):
    update = inspect.unwrap(lib_module.update.callback)
    params = list(inspect.signature(update).parameters)[2:]
    kwargs = {name: False for name in params}
    with pytest.raises(_StopUpdate):
        update(SimpleNamespace(), config, **kwargs)


def test_update_flag_readable_for_proxy(tmp_path):
    config = _Config(tmp_path)

    _run_update(config)

    assert config.seen_during_update == ("1", 0o644)
    # The finally block resets the flag; the proxy must be able to read
    # that too, or the maintenance page would stay up after the update.
    assert config.flag.read_text() == "0"
    assert stat.S_IMODE(config.flag.stat().st_mode) == 0o644
