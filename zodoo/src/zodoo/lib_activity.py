"""Last real request through the proxy (``odoo last-activity``).

The proxy writes ``proxy_exchange/last_activity`` in the run directory
(proxy/lua/activity.lua): one JSON object with the time of the last request
that looks like a person -- monitoring, health checks and the open-tab bus are
filtered out there. Hosting uses it to stop or remove idle instances.

A missing file means: no such request since the proxy started recording
(older proxy image, or nobody has opened the instance yet). Callers decide what
that means; here it is reported as ``None``, never as "now".
"""

import json
import time
from pathlib import Path

ACTIVITY_FILE = "last_activity"


def activity_path(run_dir):
    return Path(run_dir) / "proxy_exchange" / ACTIVITY_FILE


def read_last_activity(run_dir, now=None):
    """Return a dict with time/epoch/host/uri/age_seconds, or None.

    A file that cannot be parsed is reported as an error instead of None:
    silently treating it as "never active" would let an instance be removed
    because of a broken file.
    """
    path = activity_path(run_dir)
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return None
    try:
        data = json.loads(raw)
        epoch = int(data["epoch"])
    except (ValueError, KeyError, TypeError) as ex:
        raise ValueError(f"unreadable {path}: {ex}") from ex
    now = time.time() if now is None else now
    return {
        "time": data.get("time"),
        "epoch": epoch,
        "host": data.get("host"),
        "uri": data.get("uri"),
        "age_seconds": max(0, int(now - epoch)),
    }
