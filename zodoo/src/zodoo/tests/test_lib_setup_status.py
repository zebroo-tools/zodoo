"""Tests for `odoo status` output (zodoo.lib_setup._status).

The monitoring dashboard (grafana/loki, see dashboard/docker-compose.yml)
has no host port of its own -- it is published by the proxy under /system
and /logs. `odoo status` therefore has to derive those URLs from
PROXY_PORT so users can find the dashboard without reading nginx configs.
"""

from __future__ import annotations

import click

from zodoo import lib_setup as mod
from zodoo.click_config import Config


class FakeConfig(Config):
    """See test_lib_control.FakeConfig."""

    # Config reads this from the project's MANIFEST - there is none here.
    odoo_version = 16.0

    def __init__(self, **kwargs):
        self._project_name = kwargs.pop("project_name", "zodoo_unit_test")
        self._verbose = False
        self._host_run_dir = None
        self._WORKING_DIR = None
        self.force = False
        self.quiet = False
        self.restrict = {}
        self.dirs = {}
        self.commands = {}
        defaults = {
            "EXTERNAL_DOMAIN": "myhost",
            "PROXY_PORT": "8069",
            "RUN_DASHBOARD": True,
            "DASHBOARD_PASSWORD": "",
            "dbname": "mydb",
            "db_host": "postgres",
            "db_user": "odoo",
            "odoo_version": 16.0,
            "DEFAULT_DEV_PASSWORD": "1",
            "ODOO_DEMO": True,
            "ODOO_QUEUEJOBS_CHANNELS": "root:1",
            "RUN_ODOO_CRONJOBS": True,
        }
        defaults.update(kwargs)
        self.__dict__.update(defaults)
        self.files = {"project_msg": _MissingFile()}


class _MissingFile:
    def exists(self):
        return False


def _run(show_secrets=False, **kwargs):
    lines = []
    cfg = FakeConfig(**kwargs)
    orig = click.secho

    def fake_secho(text="", nl=True, **kw):
        text = str(text)
        if lines and not lines[-1][1]:
            lines[-1] = (lines[-1][0] + text, nl)
        else:
            lines.append((text, nl))

    click.secho = fake_secho
    try:
        mod._status(cfg, show_secrets=show_secrets)
    finally:
        click.secho = orig
    return [line for line, _ in lines]


def test_status_shows_monitoring_urls():
    lines = _run()
    assert "url: myhost:8069" in lines
    assert "monitoring: myhost:8069/system" in lines
    assert "logs: myhost:8069/logs" in lines


def test_status_hides_monitoring_when_dashboard_off():
    lines = _run(RUN_DASHBOARD=False)
    assert "url: myhost:8069" in lines
    assert not [x for x in lines if "monitoring" in x or "/logs" in x]


def test_status_masks_secrets_by_default():
    """`odoo update` and `odoo up -d` end with this output. On 15.10.2026 it
    put the dashboard password and DEFAULT_DEV_PASSWORD of a production
    instance into a chat transcript."""
    lines = _run(
        DASHBOARD_PASSWORD="pw-dash-123", DEFAULT_DEV_PASSWORD="pw-dev-456"
    )
    assert not [x for x in lines if "pw-dash-123" in x or "pw-dev-456" in x]
    assert "monitoring password: " + mod.MASK in lines
    assert "DEFAULT_DEV_PASSWORD:" + mod.MASK in lines


def test_status_shows_secrets_on_request():
    lines = _run(
        show_secrets=True,
        DASHBOARD_PASSWORD="secret",
        DEFAULT_DEV_PASSWORD="devpw",
    )
    assert "monitoring password: secret" in lines
    assert "DEFAULT_DEV_PASSWORD:devpw" in lines


def test_status_keeps_harmless_settings_visible():
    lines = _run()
    assert "ODOO_QUEUEJOBS_CHANNELS:root:1" in lines
    assert "ODOO_DEMO:True" in lines


def test_status_command_masks_by_default():
    """The click command itself - this is what `Commands.invoke(ctx, "status")`
    after `odoo update` runs."""
    from click.testing import CliRunner

    seen = {}
    orig = mod._status
    mod._status = lambda config, show_secrets=False: seen.update(
        s=show_secrets
    )
    try:
        CliRunner().invoke(mod.status, [], obj=FakeConfig())
        assert seen == {"s": False}
        CliRunner().invoke(mod.status, ["--show-secrets"], obj=FakeConfig())
        assert seen == {"s": True}
    finally:
        mod._status = orig


def test_status_monitoring_urls_for_every_domain():
    lines = _run(EXTERNAL_DOMAIN="a.example.com,b.example.com")
    assert "monitoring: a.example.com:8069/system" in lines
    assert "            b.example.com:8069/system" in lines


def test_status_without_external_domain_keeps_port_only():
    lines = _run(EXTERNAL_DOMAIN="")
    assert "url: :8069" in lines
    assert "monitoring: :8069/system" in lines
