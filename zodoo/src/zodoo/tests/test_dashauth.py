"""Access gate in front of /system/ and /code/ (proxy/lua/dashauth.lua).

Two layers:

* ``test_gatecore_spec`` runs the pure-Lua decision logic (gatecore.lua)
  with plain luajit: ticket signature, audience, area, expiry, single use,
  session lifetimes, cookies, settings.
* The ``proxy`` tests start the real openresty image with the real
  dashboard.conf / coding.conf / gate.http.conf and talk HTTP to it. Only the
  backend lookup is replaced by a stub that answers "backend:<uri>".
  They need Docker and skip without it.

Tickets are signed here in Python (hmac/hashlib), i.e. independently of the
Lua code -- the same way zCloud signs them.
"""

import base64
import hashlib
import hmac
import http.client
import os
import re
import secrets
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
LUA_DIR = REPO / "proxy" / "lua"
SPEC = Path(__file__).parent / "lua" / "gatecore_spec.lua"
LUA = shutil.which("luajit")
DOCKER = shutil.which("docker")
IMAGE = "openresty/openresty:alpine"

HOST = "inst-a.example.com"
KEY_SYSTEM = "system-key-" + "a" * 40
KEY_CODE = "code-key-" + "b" * 40


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_ticket(
    key, aud=HOST, area="/system", sub="user-1", iat=None, exp=None, jti=None
):
    iat = int(time.time()) if iat is None else iat
    exp = iat + 60 if exp is None else exp
    jti = jti or secrets.token_hex(16)
    payload = b64url(f"1|{aud}|{area}|{sub}|{iat}|{exp}|{jti}".encode())
    sig = hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest()
    return payload + "." + b64url(sig)


# ---------------------------------------------------------------------------
# pure Lua
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not LUA, reason="needs luajit")
def test_gatecore_spec():
    py_ticket = make_ticket(
        "py-key", aud="a.example.com", sub="py-user", iat=1000, exp=1060
    )
    out = subprocess.run(
        [LUA, str(SPEC), str(LUA_DIR), py_ticket],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    lines = out.splitlines()
    failed = [x for x in lines if not x.startswith("ok ")]
    assert not failed, "\n".join(failed)
    assert len(lines) >= 40


# ---------------------------------------------------------------------------
# real proxy
# ---------------------------------------------------------------------------

STUB_RESOLVE = (
    'access_by_lua_block { ngx.var.backend = "http://127.0.0.1:8090" }'
)


def _render_conf(tmp, legacy=False):
    """nginx.conf for the test: the gate's real files plus a stub backend.

    legacy=True: like a proxy image built before this gate -- no
    gate.http.conf (no shared dicts) and no gatecore.lua next to dashauth.lua.
    """
    conf_d = tmp / "conf.d"
    conf_d.mkdir()
    for src in (
        REPO / "dashboard" / "proxy" / "dashboard.conf",
        REPO / "coding" / "proxy" / "coding.conf",
        REPO / "coding" / "proxy" / "codevim.conf",
    ):
        text = src.read_text().replace(
            'access_by_lua_file "{lua_resolve_host}";', STUB_RESOLVE
        )
        (conf_d / src.name).write_text(text)
    shutil.copy(REPO / "proxy" / "gate.http.conf", tmp / "gate.http.conf")
    lua = tmp / "lua"
    lua.mkdir()
    for f in LUA_DIR.glob("*.lua"):
        if not (legacy and f.name == "gatecore.lua"):
            shutil.copy(f, lua / f.name)
    env_names = [
        "DEVMODE",
        "DASHBOARD_PASSWORD",
        "CODING_PASSWORD",
        "GATE_SSO_KEY_SYSTEM",
        "GATE_SSO_KEY_CODE",
        "GATE_COOKIE_SECURE",
        "GATE_SESSION_MAX_S",
        "GATE_SESSION_IDLE_S",
        "GATE_LIMIT_PER_MIN",
        "GATE_LIMIT_BURST",
    ]
    (tmp / "nginx.conf").write_text(
        "".join(f"env {n};\n" for n in env_names)
        + """
worker_processes 2;
events { worker_connections 64; }
http {
    lua_package_path "/test/lua/?.lua;;";
    """
        + ("" if legacy else "include gate.http.conf;")
        + """
    server {
        listen 8090;
        location / { default_type text/plain; return 200 "backend:$uri"; }
    }
    server {
        listen 80;
        set $default_target "http://127.0.0.1:8090";
        include /test/conf.d/*.conf;
        location / {
            proxy_pass http://127.0.0.1:8090;
        }
        location @fallback { return 502; }
    }
}
"""
    )


class Proxy:
    def __init__(self, port):
        self.port = port

    def request(self, method, path, body=None, cookies=None, host=HOST):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": host}
        if body is not None:
            body = urllib.parse.urlencode(body)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if cookies:
            headers["Cookie"] = "; ".join(
                f"{k}={v}" for k, v in cookies.items()
            )
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read().decode(errors="replace")
        set_cookies = resp.headers.get_all("Set-Cookie") or []
        conn.close()
        return resp.status, resp.headers, data, set_cookies

    def sso(self, ticket, area="/system"):
        return self.request("POST", f"{area}/__sso", {"ticket": ticket})


def _session_cookie(set_cookies, name):
    for c in set_cookies:
        m = re.match(rf"{name}=([^;]+);", c)
        if m:
            return m.group(1), c
    return None, None


@pytest.fixture(scope="module")
def start_proxy(tmp_path_factory):
    if (
        not DOCKER
        or subprocess.run([DOCKER, "info"], capture_output=True).returncode
    ):
        pytest.skip("needs docker")
    started = []

    def start(env, legacy=False):
        tmp = tmp_path_factory.mktemp("gate")
        _render_conf(tmp, legacy=legacy)
        name = f"zodoo-gate-test-{secrets.token_hex(4)}"
        cmd = [
            DOCKER,
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "-p",
            "127.0.0.1::80",
            "-v",
            f"{tmp}:/test:ro",
        ]
        for k, v in env.items():
            cmd += ["-e", f"{k}={v}"]
        cmd += [
            IMAGE,
            "openresty",
            "-c",
            "/test/nginx.conf",
            "-g",
            "daemon off;",
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        started.append(name)
        port = None
        for _ in range(50):
            out = subprocess.run(
                [DOCKER, "port", name, "80/tcp"],
                capture_output=True,
                text=True,
            ).stdout.strip()
            if out:
                port = int(out.splitlines()[0].rsplit(":", 1)[1])
                try:
                    Proxy(port).request("GET", "/health-probe")
                    break
                except OSError:
                    pass
            time.sleep(0.2)
        else:
            logs = subprocess.run(
                [DOCKER, "logs", name], capture_output=True, text=True
            )
            pytest.fail(f"proxy did not start: {logs.stdout}{logs.stderr}")
        return Proxy(port)

    yield start
    for name in started:
        subprocess.run([DOCKER, "rm", "-f", name], capture_output=True)


FULL_ENV = {
    "DEVMODE": "0",
    "DASHBOARD_PASSWORD": "dash-pw",
    "CODING_PASSWORD": "code-pw",
    "GATE_SSO_KEY_SYSTEM": KEY_SYSTEM,
    "GATE_SSO_KEY_CODE": KEY_CODE,
    # many refused tickets in a row below; the throttle has its own test
    "GATE_LIMIT_PER_MIN": "6000",
    "GATE_LIMIT_BURST": "1000",
}


@pytest.fixture(scope="module")
def proxy(start_proxy):
    return start_proxy(FULL_ENV)


def _login_sso(proxy, area="/system", key=KEY_SYSTEM):
    st, hdr, _, sc = proxy.sso(make_ticket(key, area=area), area)
    assert st == 302, (st, sc)
    name = "zodoo_gate_" + area.strip("/")
    sid, _ = _session_cookie(sc, name)
    assert sid
    return {name: sid}


# 1 -- no cookie, no access
@pytest.mark.parametrize(
    "path", ["/system/d/zodoo-overview/x", "/system/api/x", "/code/"]
)
def test_no_cookie_401(proxy, path):
    st, _, body, _ = proxy.request("GET", path)
    assert st == 401
    assert "backend:" not in body
    assert 'type="password"' in body


# 2 -- valid ticket opens without password
def test_valid_ticket_opens(proxy):
    st, hdr, _, sc = proxy.sso(make_ticket(KEY_SYSTEM))
    assert st == 302
    assert hdr["Location"].endswith("/system/")
    sid, raw = _session_cookie(sc, "zodoo_gate_system")
    assert sid
    for attr in ("Secure", "HttpOnly", "Path=/system/", "SameSite=Lax"):
        assert attr in raw, raw
    st, _, body, _ = proxy.request(
        "GET",
        "/system/d/zodoo-overview/x",
        cookies={"zodoo_gate_system": sid},
    )
    assert st == 200 and body == "backend:/system/d/zodoo-overview/x"


def test_valid_code_ticket_opens_code(proxy):
    ck = _login_sso(proxy, "/code", KEY_CODE)
    st, _, body, _ = proxy.request("GET", "/code/", cookies=ck)
    assert st == 200 and body == "backend:/code/"


# 3 -- refused tickets
def _tampered_sig():
    t = make_ticket(KEY_SYSTEM)
    return t[:-1] + ("A" if t[-1] != "A" else "B")


def _tampered_payload():
    t = make_ticket(KEY_SYSTEM)
    payload, sig = t.split(".")
    now = int(time.time())
    forged = b64url(
        f"1|{HOST}|/system|admin|{now}|{now + 60}|{'f' * 32}".encode()
    )
    return forged + "." + sig


@pytest.mark.parametrize(
    "ticket",
    [
        pytest.param(
            lambda: make_ticket(
                KEY_SYSTEM,
                iat=int(time.time()) - 200,
                exp=int(time.time()) - 100,
            ),
            id="expired",
        ),
        pytest.param(_tampered_sig, id="signature"),
        pytest.param(_tampered_payload, id="payload"),
        pytest.param(
            lambda: make_ticket(KEY_SYSTEM, aud="inst-b.example.com"),
            id="other-instance",
        ),
        pytest.param(
            lambda: make_ticket(KEY_SYSTEM, area="/code"), id="code-area"
        ),
        pytest.param(lambda: make_ticket(KEY_CODE), id="code-key"),
        pytest.param(lambda: "", id="empty"),
    ],
)
def test_refused_ticket(proxy, ticket):
    st, _, body, sc = proxy.sso(ticket())
    assert st == 401
    assert "abgelaufen" in body
    assert not _session_cookie(sc, "zodoo_gate_system")[0]


def test_ticket_used_twice(proxy):
    t = make_ticket(KEY_SYSTEM)
    assert proxy.sso(t)[0] == 302
    st, _, _, sc = proxy.sso(t)
    assert st == 401
    assert not _session_cookie(sc, "zodoo_gate_system")[0]


def test_ticket_in_url_refused(proxy):
    t = make_ticket(KEY_SYSTEM)
    st, _, _, sc = proxy.request("GET", "/system/__sso?ticket=" + t)
    assert st == 401
    assert not _session_cookie(sc, "zodoo_gate_system")[0]
    # and the ticket was not consumed by the GET either
    assert proxy.sso(t)[0] == 302


def test_ticket_for_other_host_header(proxy):
    st, *_ = proxy.request(
        "POST",
        "/system/__sso",
        {"ticket": make_ticket(KEY_SYSTEM)},
        host="inst-b.example.com",
    )
    assert st == 401


# 4 -- cookies of the two areas are separate
def test_code_cookie_does_not_open_system(proxy):
    ck = _login_sso(proxy, "/code", KEY_CODE)
    st, *_ = proxy.request(
        "GET",
        "/system/api/x",
        cookies={"zodoo_gate_system": ck["zodoo_gate_code"]},
    )
    assert st == 401


def test_system_cookie_does_not_open_code(proxy):
    ck = _login_sso(proxy)
    st, *_ = proxy.request(
        "GET", "/code/", cookies={"zodoo_gate_code": ck["zodoo_gate_system"]}
    )
    assert st == 401


# 5 -- logout
def test_logout(proxy):
    ck = _login_sso(proxy)
    assert proxy.request("GET", "/system/api/x", cookies=ck)[0] == 200
    st, hdr, _, sc = proxy.request("GET", "/system/__logout", cookies=ck)
    assert st == 302 and hdr["Location"].endswith("/system/")
    assert any(
        c.startswith("zodoo_gate_system=;") and "Max-Age=0" in c for c in sc
    )
    assert proxy.request("GET", "/system/api/x", cookies=ck)[0] == 401


# 6 -- lifetimes (shortened)
def test_idle_timeout(start_proxy):
    p = start_proxy(
        dict(FULL_ENV, GATE_SESSION_IDLE_S="2", GATE_SESSION_MAX_S="60")
    )
    ck = _login_sso(p)
    assert p.request("GET", "/system/api/x", cookies=ck)[0] == 200
    time.sleep(3.2)
    assert p.request("GET", "/system/api/x", cookies=ck)[0] == 401


def test_absolute_timeout(start_proxy):
    p = start_proxy(
        dict(FULL_ENV, GATE_SESSION_IDLE_S="3", GATE_SESSION_MAX_S="4")
    )
    ck = _login_sso(p)
    for _ in range(3):  # keep it busy, the idle window never runs out
        assert p.request("GET", "/system/api/x", cookies=ck)[0] == 200
        time.sleep(1.2)
    time.sleep(1.5)
    assert p.request("GET", "/system/api/x", cookies=ck)[0] == 401


# 7 -- password fallback
def test_password_right(proxy):
    st, hdr, _, sc = proxy.request(
        "POST", "/system/__auth", {"password": "dash-pw"}
    )
    assert st == 302
    sid, raw = _session_cookie(sc, "zodoo_gate_system")
    assert sid and "Path=/system/" in raw and "Secure" in raw
    st, *_ = proxy.request(
        "GET", "/system/api/x", cookies={"zodoo_gate_system": sid}
    )
    assert st == 200


def test_password_wrong(proxy):
    st, _, body, sc = proxy.request(
        "POST", "/code/__auth", {"password": "nope"}
    )
    assert st == 401 and "Falsches Passwort" in body
    assert not _session_cookie(sc, "zodoo_gate_code")[0]


def test_password_of_other_area(proxy):
    st, *_ = proxy.request("POST", "/code/__auth", {"password": "dash-pw"})
    assert st == 401


def test_old_cookie_is_not_accepted(proxy):
    """The previous gate's cookie (HMAC of the password) opens nothing."""
    old = base64.b64encode(
        hmac.new(
            b"zodoo-dashboard-gate", b"zodoo_gate_system:dash-pw", "sha1"
        ).digest()
    ).decode()
    st, *_ = proxy.request(
        "GET", "/system/api/x", cookies={"zodoo_gate_system": old}
    )
    assert st == 401


def _defaults(env):
    return {k: v for k, v in env.items() if not k.startswith("GATE_LIMIT_")}


def test_rate_limit_password(start_proxy):
    p = start_proxy(_defaults(FULL_ENV))
    codes = [
        p.request("POST", "/system/__auth", {"password": "x"})[0]
        for _ in range(12)
    ]
    assert codes[:5] == [401] * 5 and 429 in codes, codes
    # the budget is used up for the right password too
    assert p.request("POST", "/system/__auth", {"password": "dash-pw"})[0] == (
        429
    )


def test_rate_limit_ticket(start_proxy):
    p = start_proxy(_defaults(FULL_ENV))
    codes = [p.sso("x")[0] for _ in range(12)]
    assert 429 in codes, codes


def test_successful_logins_are_not_throttled(start_proxy):
    """A team behind one router address opens the dashboard many times."""
    p = start_proxy(_defaults(FULL_ENV))
    for _ in range(20):
        assert p.sso(make_ticket(KEY_SYSTEM))[0] == 302


def test_no_password_outside_devmode_503(start_proxy):
    p = start_proxy({"DEVMODE": "0"})
    for path in ("/system/api/x", "/code/", "/system/__auth"):
        st, _, body, _ = p.request("GET", path)
        assert st == 503, path
        assert "backend:" not in body


def test_devmode_without_password_open(start_proxy):
    p = start_proxy({"DEVMODE": "1"})
    assert p.request("GET", "/system/api/x")[0] == 200
    assert p.request("GET", "/code/")[0] == 200


def test_devmode_cookie_not_secure(start_proxy):
    p = start_proxy({"DEVMODE": "1", "DASHBOARD_PASSWORD": "pw"})
    st, _, _, sc = p.request("POST", "/system/__auth", {"password": "pw"})
    sid, raw = _session_cookie(sc, "zodoo_gate_system")
    assert st == 302 and sid and "Secure" not in raw


# backward compatible: no SSO keys, password and the old zCloud form work
def test_without_sso_keys_password_works(start_proxy):
    p = start_proxy(
        {"DEVMODE": "0", "DASHBOARD_PASSWORD": "pw", "CODING_PASSWORD": "cp"}
    )
    # old zCloud button: a form POSTing the password to /system/__auth
    st, hdr, _, sc = p.request("POST", "/system/__auth", {"password": "pw"})
    assert st == 302
    sid, _ = _session_cookie(sc, "zodoo_gate_system")
    st, *_ = p.request(
        "GET", "/system/api/x", cookies={"zodoo_gate_system": sid}
    )
    assert st == 200
    # an SSO ticket cannot open anything without a key
    st, *_ = p.sso(make_ticket(KEY_SYSTEM))
    assert st == 401
    st, _, _, sc = p.request("POST", "/code/__auth", {"password": "cp"})
    assert st == 302


def test_old_proxy_image_keeps_password_gate(start_proxy):
    """New dashauth.lua (mounted from ~/.odoo/images) on a proxy that was not
    rebuilt yet: no gatecore, no shared dicts. The old gate keeps working."""
    p = start_proxy(dict(FULL_ENV), legacy=True)
    assert p.request("GET", "/system/api/x")[0] == 401
    st, _, _, sc = p.request("POST", "/system/__auth", {"password": "dash-pw"})
    assert st == 302
    sid, raw = _session_cookie(sc, "zodoo_gate_system")
    assert sid and "Path=/;" in raw
    st, *_ = p.request(
        "GET", "/system/api/x", cookies={"zodoo_gate_system": sid}
    )
    assert st == 200


def test_sso_only_without_password(start_proxy):
    p = start_proxy({"DEVMODE": "0", "GATE_SSO_KEY_SYSTEM": KEY_SYSTEM})
    st, _, body, _ = p.request("GET", "/system/api/x")
    assert st == 401 and 'type="password"' not in body
    st, *_ = p.request("POST", "/system/__auth", {"password": ""})
    assert st == 401
    assert p.sso(make_ticket(KEY_SYSTEM))[0] == 302


# 9 -- regression: entry points and shop URLs
@pytest.mark.parametrize(
    "path,location",
    [
        ("/system", "/system/d/zodoo-overview/zodoo-instance-overview?kiosk"),
        ("/system/", "/system/d/zodoo-overview/zodoo-instance-overview?kiosk"),
        ("/logs", "/system/d/zodoo-logs/zodoo-logs"),
        ("/codevim", "/code/?vim=1"),
        ("/novim", "/code/?vim=0"),
    ],
)
def test_entry_redirects(proxy, path, location):
    st, hdr, _, _ = proxy.request("GET", path)
    assert st == 302 and hdr["Location"] == location


def test_shop_url_starting_with_system_reaches_odoo(proxy):
    st, _, body, _ = proxy.request("GET", "/systemregal-fur-druckerfarm-7716")
    assert st == 200 and body == "backend:/systemregal-fur-druckerfarm-7716"


def test_logout_link_in_dashboards():
    for name in ("zodoo-overview.json", "zodoo-logs.json"):
        text = (
            REPO / "dashboard" / "grafana" / "dashboards" / name
        ).read_text()
        assert 'href=\\"/system/__logout\\" target=\\"_self\\"' in text, name


def test_proxy_image_ships_gate_files():
    dockerfile = (REPO / "proxy" / "Dockerfile").read_text()
    assert "lua/gatecore.lua" in dockerfile
    assert "gate.http.conf" in dockerfile
    assert (
        "include gate.http.conf;"
        in (REPO / "proxy" / "nginx.conf").read_text()
    )


if os.environ.get("ZODOO_GATE_KEEP"):  # pragma: no cover - debugging aid
    pass
