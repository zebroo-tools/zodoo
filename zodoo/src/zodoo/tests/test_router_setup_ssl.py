"""bin/setup_ssl.py: where the TLS directives of a certbot vhost end up.

Since the HTTP->HTTPS redirect block was put in front of the proxy block
(_http_redirect.inc), two server blocks listen on port 80 for the same name.
'certbot --nginx' picked the first one and wrote 'listen 443 ssl' into the
redirect block, so HTTPS answered with a 301 to itself. That hit
quattro-test-machine-3c305b.zebroo.de on 2026-10-15, its first certificate.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_ROUTER = Path(__file__).resolve().parents[4] / "router_global"
_SCRIPT = _ROUTER / "files" / "bin" / "setup_ssl.py"
_TEMPLATES = _ROUTER / "templates"

DOMAIN = "example.zebroo.de"


def _load():
    spec = importlib.util.spec_from_file_location("setup_ssl", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _render(template="upstream"):
    from jinja2 import Environment, FileSystemLoader

    item = {
        "template": template,
        "server_name": DOMAIN,
        "upstream_name": "upstream_1",
        "upstream_server": "192.168.77.42",
        "upstream_port": 8444,
        "timeout": 600,
        "use_certbot": True,
    }
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)))
    return env.get_template(template).render(item=item)


def _blocks(text):
    """Top-level server blocks as text, in file order."""
    blocks, depth, start = [], 0, None
    for m in re.finditer(r"server\s*\{|\{|\}", text):
        tok = m.group(0)
        if tok.startswith("server") and depth == 0:
            start = m.start()
            depth = 1
        elif tok == "{" and depth:
            depth += 1
        elif tok == "}" and depth:
            depth -= 1
            if depth == 0:
                blocks.append(text[start : m.end()])
    return blocks


@pytest.fixture
def anlage(tmp_path):
    project = tmp_path / "proxy"
    (project / "sites-enabled").mkdir(parents=True)
    le = project / "letsencrypt"
    le.mkdir()
    (le / "options-ssl-nginx.conf").write_text("")
    (le / "ssl-dhparams.pem").write_text("")
    return project


def _fake_certbot(project, aufrufe):
    def run(*args):
        aufrufe.append(args)
        if args[0] == "certonly":
            (project / "letsencrypt" / "live" / DOMAIN).mkdir(parents=True)

    return run


@pytest.mark.parametrize("template", ["upstream", "upstream_direct_odoo"])
@pytest.mark.parametrize("cert_vorhanden", [False, True])
def test_tls_lands_in_proxy_block_not_in_redirect(anlage, template, cert_vorhanden):
    mod = _load()
    if cert_vorhanden:
        (anlage / "letsencrypt" / "live" / DOMAIN).mkdir(parents=True)
    vhost = anlage / "sites-enabled" / DOMAIN
    vhost.write_text(_render(template))
    aufrufe = []

    mod.setup(anlage, vhost, DOMAIN, run=_fake_certbot(anlage, aufrufe))

    blocks = _blocks(vhost.read_text())
    redirect = [b for b in blocks if "return 301 https://" in b]
    proxy = [b for b in blocks if "proxy_pass" in b]
    assert redirect and proxy
    assert "listen 443" not in redirect[0]
    assert "listen 80;" in redirect[0]
    assert proxy[0].count("listen 443 ssl;") == 1
    assert "/etc/letsencrypt/live/%s/fullchain.pem" % DOMAIN in proxy[0]
    # certbot must not have edited the file itself
    assert all(a[0] != "install" for a in aufrufe)
    if cert_vorhanden:
        assert aufrufe == []  # no ACME call for an existing cert
    else:
        assert aufrufe[0][:2] == ("certonly", "--nginx")
        assert "--deploy-hook" in aufrufe[0]


def test_lines_carry_certbot_marker_for_fast_restore(anlage):
    """lib_router recognises the TLS binding by '# managed by Certbot'."""
    from .. import lib_router

    mod = _load()
    (anlage / "letsencrypt" / "live" / DOMAIN).mkdir(parents=True)
    vhost = anlage / "sites-enabled" / DOMAIN
    vhost.write_text(_render())
    mod.setup(anlage, vhost, DOMAIN, run=lambda *a: None)

    zeilen = lib_router._certbot_directive_lines(vhost.read_text())
    assert any("listen 443 ssl" in z for z in zeilen)
    assert any("ssl_certificate_key" in z for z in zeilen)


def test_missing_le_includes_are_left_out(anlage):
    """An include of a missing file would fail 'nginx -t' for the router."""
    mod = _load()
    (anlage / "letsencrypt" / "ssl-dhparams.pem").unlink()
    lines = mod.tls_lines(anlage, DOMAIN)
    assert not any("ssl_dhparam" in x for x in lines)
    assert any("options-ssl-nginx.conf" in x for x in lines)


def test_without_placeholder_falls_back_to_certbot_install(anlage):
    mod = _load()
    (anlage / "letsencrypt" / "live" / DOMAIN).mkdir(parents=True)
    vhost = anlage / "sites-enabled" / DOMAIN
    vhost.write_text("server {\n    server_name %s;\n}\n" % DOMAIN)
    aufrufe = []
    mod.setup(anlage, vhost, DOMAIN, run=lambda *a: aufrufe.append(a))
    assert aufrufe and aufrufe[0][0] == "install"
