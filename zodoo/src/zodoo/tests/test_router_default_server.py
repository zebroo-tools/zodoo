"""The catch-all vhost that keeps stray requests out of a real site.

The bug this guards against is quiet: nginx makes the first server block it
parses the default for every unmatched name, the blocks come in by filename,
so a new vhost sorting first inherits all stray traffic. That is how
"3dm-monitoring.zebroo.de" started answering for the bare router IP.
"""

from __future__ import annotations

from pathlib import Path

_TEMPLATES = Path(__file__).resolve().parents[4] / "router_global" / "templates"


def _render_default_server():
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    from zodoo.lib_router import _DEFAULT_SERVER_VHOST

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        undefined=StrictUndefined,
        keep_trailing_newline=False,
        trim_blocks=True,
        lstrip_blocks=False,
    )
    return env.get_template("default_server").render(item=_DEFAULT_SERVER_VHOST)


def test_catch_all_is_the_default_on_both_ports():
    out = _render_default_server()
    assert "listen 80 default_server;" in out
    assert "listen 443 ssl default_server;" in out
    assert "server_name _;" in out


def test_catch_all_answers_404():
    """404, not 444: a dropped connection reads like an outage, and the
    router's own health check in Zabbix asks for exactly this status."""
    assert "return 404;" in _render_default_server()


def test_acme_challenge_stays_reachable():
    """A certificate is validated before the vhost it belongs to exists, so
    the catch-all must not swallow the challenge."""
    out = _render_default_server()
    assert "location /.well-known/acme-challenge/" in out


def test_certificate_paths_point_at_the_self_signed_pair():
    out = _render_default_server()
    assert "/etc/ssl/custom_ssl/_default/server.crt" in out
    assert "/etc/ssl/custom_ssl/_default/server.key" in out


def test_appended_to_a_normal_vhost_list():
    from zodoo.lib_router import _with_default_server

    vhosts = [{"template": "upstream", "server_name": "a.zebroo.de"}]
    out = _with_default_server(vhosts)

    assert len(out) == 2
    assert out[0] is vhosts[0], "existing vhosts must be passed through as-is"
    assert out[-1]["template"] == "default_server"
    assert vhosts == [{"template": "upstream", "server_name": "a.zebroo.de"}], (
        "the caller's list must not be mutated"
    )


def test_a_hand_written_catch_all_wins():
    """A router that needs a different catch-all keeps the one from
    vhosts.yml - we must not deploy two default_server blocks, nginx refuses
    the whole configuration then."""
    from zodoo.lib_router import _with_default_server

    own = {"template": "default_server", "server_name": "own.invalid"}
    assert _with_default_server([own]) == [own]


def test_self_signed_cert_is_requested_for_a_usable_name():
    """The name reaches openssl as CN and SAN - "_" is not a DNS name."""
    from zodoo.lib_router import _DEFAULT_SERVER_VHOST

    assert _DEFAULT_SERVER_VHOST["ssl_self_signed"] is True
    assert _DEFAULT_SERVER_VHOST["server_name"].endswith(".invalid")
