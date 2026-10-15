"""`odoo last-activity` and the proxy filter behind it (proxy/lua/activity.lua).

Hosting stops and removes instances based on this value, so the cases that
matter most are the ones that would keep an idle instance "active" forever
(monitoring, the open-tab bus) and the ones that would make a used instance
look idle (a broken file read as "never").
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from zodoo import lib_control
from zodoo.lib_activity import activity_path, read_last_activity
from zodoo.tests.test_lib_control import FakeConfig

REPO = Path(__file__).resolve().parents[4]
ACTIVITY_LUA = REPO / "proxy" / "lua" / "activity.lua"


def _write(run_dir, payload):
    path = activity_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload)
    return path


# ---------------------------------------------------------------------------
# read_last_activity
# ---------------------------------------------------------------------------


def test_missing_file_is_none(tmp_path):
    assert read_last_activity(tmp_path) is None


def test_reads_file_written_by_proxy(tmp_path):
    _write(
        tmp_path,
        '{"time":"2026-10-01T10:00:00Z","epoch":1790848800,'
        '"host":"x.zebroo.de","uri":"/odoo"}\n',
    )
    info = read_last_activity(tmp_path, now=1790848800 + 3 * 86400 + 5)
    assert info["time"] == "2026-10-01T10:00:00Z"
    assert info["host"] == "x.zebroo.de"
    assert info["uri"] == "/odoo"
    assert info["age_seconds"] == 3 * 86400 + 5


def test_broken_file_is_an_error_not_never(tmp_path):
    _write(tmp_path, '{"time": "half')
    with pytest.raises(ValueError):
        read_last_activity(tmp_path)


def test_clock_skew_never_gives_negative_age(tmp_path):
    _write(tmp_path, '{"epoch": 2000}')
    assert read_last_activity(tmp_path, now=1000)["age_seconds"] == 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _invoke(tmp_path, *args):
    cfg = FakeConfig(dirs={"run": tmp_path})
    return CliRunner().invoke(lib_control.last_activity, list(args), obj=cfg)


def test_cli_none(tmp_path):
    res = _invoke(tmp_path)
    assert res.exit_code == 0
    assert res.output.strip() == "none"


def test_cli_json(tmp_path):
    _write(tmp_path, '{"time":"t","epoch":100,"host":"h","uri":"/u"}')
    res = _invoke(tmp_path, "--json")
    assert res.exit_code == 0
    data = json.loads(res.output)["last_activity"]
    assert data["epoch"] == 100 and data["host"] == "h"


def test_cli_json_none(tmp_path):
    res = _invoke(tmp_path, "--json")
    assert json.loads(res.output) == {"last_activity": None}


def test_cli_broken_file_fails(tmp_path):
    _write(tmp_path, "garbage")
    res = _invoke(tmp_path)
    assert res.exit_code != 0


# ---------------------------------------------------------------------------
# proxy filter (pure Lua, runs without openresty)
# ---------------------------------------------------------------------------

LUA = shutil.which("luajit") or shutil.which("lua")

BROWSER = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

CASES = [
    # (method, uri, user agent, counts as activity)
    ("GET", "/odoo", BROWSER, True),
    (
        "POST",
        "/web/dataset/call_kw/res.partner/web_search_read",
        BROWSER,
        True,
    ),
    ("GET", "/web/login", BROWSER, True),
    ("GET", "/code/", BROWSER, True),
    ("GET", "/web/health", BROWSER, False),
    ("GET", "/websocket", BROWSER, False),
    ("POST", "/longpolling/poll", BROWSER, False),
    ("POST", "/bus/im_status", BROWSER, False),
    ("GET", "/system/api/dashboards", BROWSER, False),
    ("HEAD", "/odoo", BROWSER, False),
    ("GET", "/web/login", "python-requests/2.31.0", False),
    ("GET", "/web/login", "curl/8.5.0", False),
    ("GET", "/web/login", "Gatus/1.0", False),
    ("GET", "/web/login", "Zabbix", False),
    ("GET", "/web/login", "Go-http-client/1.1", False),
    ("GET", "/web/login", "node", False),
    ("GET", "/", "Mozilla/5.0 (compatible; Googlebot/2.1)", False),
    ("GET", "/web/login", "", False),
]


@pytest.mark.skipif(not LUA, reason="needs luajit or lua")
def test_proxy_filter(tmp_path):
    script = tmp_path / "check.lua"
    lines = [
        f"package.path = {json.dumps(str(ACTIVITY_LUA.parent) + '/?.lua;')} .. package.path",
        'local a = require("activity")',
    ]
    for method, uri, ua, _ in CASES:
        lines.append(
            "print(tostring(a.is_activity(%s, %s, %s)))"
            % (json.dumps(method), json.dumps(uri), json.dumps(ua))
        )
    script.write_text("\n".join(lines) + "\n")
    out = subprocess.run(
        [LUA, str(script)], capture_output=True, text=True, check=True
    )
    got = out.stdout.split()
    for (method, uri, ua, want), result in zip(CASES, got):
        assert result == str(want).lower(), (method, uri, ua)
    assert len(got) == len(CASES)


@pytest.mark.skipif(not LUA, reason="needs luajit or lua")
def test_proxy_file_is_readable_by_cli(tmp_path):
    """What the proxy writes is what the CLI reads (quotes in host escaped)."""
    target = activity_path(tmp_path)
    target.parent.mkdir(parents=True)
    script = tmp_path / "write.lua"
    script.write_text(
        f"package.path = {json.dumps(str(ACTIVITY_LUA.parent) + '/?.lua;')} .. package.path\n"
        'local a = require("activity")\n'
        f'assert(a.write({json.dumps(str(target))}, a.render(1790848800, \'we"ird\\\\host\', "/odoo")))\n'
    )
    subprocess.run([LUA, str(script)], check=True)
    info = read_last_activity(tmp_path, now=1790848800)
    assert info["time"] == "2026-10-01T10:00:00Z"
    assert info["host"] == 'we"ird\\host'
    assert info["uri"] == "/odoo"
    assert not (target.parent / "last_activity.tmp").exists()
