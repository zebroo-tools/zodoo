"""Port 80 of a TLS vhost: who answers it, and with what.

The redirect used to be rendered only for vhosts that carry their own
certificate. For use_certbot vhosts it was left to certbot - and certbot
writes it into the delivered file, which the next render overwrites.
_reinstall_certbot_tls carries back the TLS directives only (a server block
must not be nested inside another one), so the redirect was gone for good.

On hy-router that had reached 17 of 163 vhosts, hosting.zebroo.de and
ntfy.zebroo.de among them. It stayed invisible as long as some arbitrary
other vhost happened to be nginx's default server; once the catch-all vhost
took that over on 2026-10-14, those names answered 404 on plain HTTP.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_TEMPLATES = (
    Path(__file__).resolve().parents[4] / "router_global" / "templates"
)

# All three render a vhost that can terminate TLS, so all three need the
# redirect. Testing one of them would let the other two drift away unnoticed.
_TLS_TEMPLATES = ("upstream", "upstream_direct_odoo", "static_files")


def _render(template, **over):
    from jinja2 import Environment, FileSystemLoader

    item = {
        "template": template,
        "server_name": "example.zebroo.de",
        "upstream_name": "upstream_1",
        "upstream_server": "192.168.77.42",
        "upstream_port": 8444,
        "timeout": 600,
    }
    item.update(over)
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        keep_trailing_newline=False,
        trim_blocks=True,
        lstrip_blocks=False,
    )
    return env.get_template(template).render(item=item)


def _redirect_block(rendered):
    """The server block that listens on plain port 80, or None."""
    for block in rendered.split("server {"):
        if "listen 80;" in block.split("}")[0] + "}":
            return "server {" + block
    return None


@pytest.mark.parametrize("template", _TLS_TEMPLATES)
def test_certbot_vhost_answers_on_port_80(template):
    """The regression itself: certbot vhosts had no port-80 block at all."""
    block = _redirect_block(_render(template, use_certbot=True))
    assert block is not None, "no listen-80 server block was rendered"
    assert "server_name  example.zebroo.de;" in block
    assert "return 301 https://$host$request_uri;" in block


@pytest.mark.parametrize("template", _TLS_TEMPLATES)
def test_certbot_vhost_keeps_acme_reachable_over_http(template):
    """Redirecting everything would break issuing the first certificate.

    HTTP-01 is validated over plain HTTP, and at that point there is no
    certificate to serve the redirect target with - so the challenge path has
    to be answered, not redirected. "^~" because a prefix match must win
    against any regex location.
    """
    block = _redirect_block(_render(template, use_certbot=True))
    assert "location ^~ /.well-known/acme-challenge/ {" in block
    # The ACME location has to come first; after "return 301" nginx would
    # never reach it.
    assert block.index("acme-challenge") < block.index("return 301")


@pytest.mark.parametrize("template", _TLS_TEMPLATES)
def test_own_certificate_vhost_still_redirects_without_acme(template):
    """What worked before must keep working, and gain nothing it has no use for."""
    block = _redirect_block(_render(template, ssl_self_signed=True))
    assert block is not None
    assert "return 301 https://$host$request_uri;" in block
    assert "acme-challenge" not in block


@pytest.mark.parametrize("template", _TLS_TEMPLATES)
def test_plain_http_vhost_gets_no_redirect(template):
    """A vhost without TLS must not get one - it would shadow the real block.

    Its own server block is the one serving port 80. A second block for the
    same name, rendered first, would take every request and bounce it to a
    port nothing listens on.
    """
    rendered = _render(template)
    assert "return 301 https://$host$request_uri;" not in rendered


@pytest.mark.parametrize("template", _TLS_TEMPLATES)
def test_exactly_one_port_80_block(template):
    """Two blocks for one name make nginx drop one of them with a warning."""
    rendered = _render(template, use_certbot=True)
    assert rendered.count("listen 80;") == 1
