# Part of Zebroo GmbH. See LICENSE file for full copyright and licensing details (www.zebroo.de/license).
"""Unit tests for the monitoring dashboard service.

Fast, no Docker: they exercise the dashboard generator and the custom Odoo
metrics exporter's pure helpers. The exporter's third-party imports
(psycopg2, prometheus_client) are stubbed so the module loads in the plain
test venv.
"""

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path
from unittest import mock

# repo root: .../zodoo/src/zodoo/tests/test_dashboard.py -> parents[4]
REPO_ROOT = Path(__file__).resolve().parents[4]
DASHBOARDS = REPO_ROOT / "dashboard" / "grafana" / "dashboards"
GENERATOR = REPO_ROOT / "dashboard" / "grafana" / "generate_dashboard.py"
EXPORTER = REPO_ROOT / "dashboard" / "exporter" / "app.py"


def test_committed_dashboards_are_valid_json():
    for name, min_panels in (("zodoo-overview", 20), ("zodoo-logs", 3)):
        data = json.loads((DASHBOARDS / f"{name}.json").read_text())
        assert data["uid"] == name
        panels = [p for p in data["panels"] if p.get("type") != "row"]
        assert len(panels) >= min_panels


def test_generator_matches_committed(tmp_path):
    """The committed JSON must equal a fresh generator run (no drift)."""
    workdir = tmp_path / "grafana"
    (workdir / "dashboards").mkdir(parents=True)
    shutil.copy(GENERATOR, workdir / "generate_dashboard.py")

    subprocess.run(
        [sys.executable, str(workdir / "generate_dashboard.py")],
        check=True,
        cwd=tmp_path,
    )

    for name in ("zodoo-overview", "zodoo-logs"):
        generated = json.loads(
            (workdir / "dashboards" / f"{name}.json").read_text()
        )
        committed = json.loads((DASHBOARDS / f"{name}.json").read_text())
        assert generated == committed, (
            f"{name}.json is out of date -- rerun "
            "dashboard/grafana/generate_dashboard.py"
        )


def test_nav_links_bypass_grafana_router():
    """Link bar targets must be loaded by the browser, not Grafana's router.

    Grafana routes clicks on links without a target inside its app below
    root_url /system/, so /logs ended up as /system/logs (page not found).
    Every link needs target="_self" and has to hit a proxy entry point.
    """
    conf = (REPO_ROOT / "dashboard" / "proxy" / "dashboard.conf").read_text()
    for name in ("zodoo-overview", "zodoo-logs"):
        data = json.loads((DASHBOARDS / f"{name}.json").read_text())
        content = data["panels"][0]["options"]["content"]
        anchors = re.findall(r"<a ([^>]*)>", content)
        assert anchors, f"{name}: no links in the link bar"
        for attrs in anchors:
            assert 'target="_self"' in attrs, f"{name}: {attrs}"
            href = re.search(r'href="([^"]+)"', attrs).group(1)
            assert f"location = {href} " in conf, f"{name}: {href}"


def test_logs_list_reaches_back():
    # The log list used to hold Grafana's default of 1000 lines, and the
    # proxy access log filled them within seconds: a wider time range
    # seemed to change nothing.
    data = json.loads((DASHBOARDS / "zodoo-logs.json").read_text())
    names = [v["name"] for v in data["templating"]["list"]]
    assert "proxylog" in names
    proxylog = next(
        v for v in data["templating"]["list"] if v["name"] == "proxylog"
    )
    assert proxylog["current"]["value"] == ".+_proxy"
    (logs_panel,) = [p for p in data["panels"] if p["type"] == "logs"]
    target = logs_panel["targets"][0]
    assert target["maxLines"] == 5000
    assert 'container!~"$proxylog"' in target["expr"]


def test_loki_queries_span_retention():
    conf = (REPO_ROOT / "dashboard" / "config" / "loki-config.yml").read_text()
    assert "max_query_length: ${DASHBOARD_LOKI_RETENTION}" in conf


def test_odoo_run_sets_werkzeug_level():
    # odoo-bin appends --log-handler to the config file's log_handler, which
    # sets werkzeug:DEBUG; without an explicit werkzeug entry every request
    # was logged despite ODOO_LOG_LEVEL=warn.
    run_py = (REPO_ROOT / "odoo" / "bin" / "run.py").read_text()
    assert '"--log-handler=werkzeug:{LEVEL.upper()}"' in run_py


def _load_exporter(monkeypatch):
    """Import dashboard/exporter/app.py with its heavy deps stubbed."""
    monkeypatch.setitem(sys.modules, "psycopg2", mock.MagicMock())
    pc = types.ModuleType("prometheus_client")
    pc.start_http_server = lambda *a, **k: None
    core = types.ModuleType("prometheus_client.core")
    core.REGISTRY = mock.MagicMock()
    core.GaugeMetricFamily = mock.MagicMock()
    pc.core = core
    monkeypatch.setitem(sys.modules, "prometheus_client", pc)
    monkeypatch.setitem(sys.modules, "prometheus_client.core", core)

    spec = importlib.util.spec_from_file_location(
        "dash_exporter_app", EXPORTER
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_queuejob_workers_parsing(monkeypatch):
    app = _load_exporter(monkeypatch)
    monkeypatch.setenv("ODOO_QUEUEJOBS_CHANNELS", "root:2,foo:4")
    assert app._queuejob_workers() == 6.0
    monkeypatch.setenv("ODOO_QUEUEJOBS_CHANNELS", "root:1")
    assert app._queuejob_workers() == 1.0
    monkeypatch.setenv("ODOO_QUEUEJOBS_CHANNELS", "")
    assert app._queuejob_workers() == 0.0
    # malformed entries are ignored, not fatal
    monkeypatch.setenv("ODOO_QUEUEJOBS_CHANNELS", "garbage,root:3")
    assert app._queuejob_workers() == 3.0


def test_float_env_handles_missing_and_bad(monkeypatch):
    app = _load_exporter(monkeypatch)
    monkeypatch.setenv("SOME_INT", "4")
    assert app._float_env("SOME_INT") == 4.0
    monkeypatch.delenv("SOME_MISSING", raising=False)
    assert app._float_env("SOME_MISSING") != app._float_env(
        "SOME_MISSING"
    )  # NaN
    monkeypatch.setenv("SOME_BAD", "notanumber")
    assert app._float_env("SOME_BAD") != app._float_env("SOME_BAD")  # NaN
