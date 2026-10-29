# Monitoring dashboard

Every instance can bring its own small monitoring stack: Grafana, Prometheus,
Loki, Alloy and a few exporters. It is off by default and switched on per
instance:

```bash
odoo setting RUN_DASHBOARD=1
odoo reload && odoo up -d
```

The other `DASHBOARD_*` settings (retention, remote write, which container logs
are collected) are described in `dashboard/default.settings`.

## Entry points

The dashboard is served by the instance's own proxy, on the same host as Odoo:

| URL       | Opens                                                 |
| --------- | ----------------------------------------------------- |
| `/system` | Instance overview, in kiosk mode (no Grafana top bar) |
| `/logs`   | Log viewer with search and filter bar                 |
| `/logs2`  | Old bookmark — just redirects to `/logs`              |

These three are redirects in the proxy (`dashboard/proxy/dashboard.conf`).
Grafana itself lives below `/system/` (`root_url` with
`serve_from_sub_path`), so the real dashboard addresses look like
`/system/d/zodoo-logs/zodoo-logs`.

Both URLs ask for `DASHBOARD_PASSWORD` — a password only, no user name. On
non-DEVMODE instances it is generated automatically; `odoo status
--show-secrets` shows it. In DEVMODE the password is empty and there is no
prompt.

## The link bar

At the top of both dashboards sits a link bar: **Overview | Logs**. It points
at `/system` and `/logs`, i.e. at the proxy redirects above, so the overview
always opens in kiosk mode.

The links carry `target="_self"`. Without it Grafana catches the click and
resolves the link inside its own app below `/system/` — `/logs` turned into
`/system/logs` and showed "Page not found". If you add a link to the bar
(`nav()` in `dashboard/grafana/generate_dashboard.py`), keep the target.

The dashboards are generated; after a change run

```bash
python3 dashboard/grafana/generate_dashboard.py
```

and commit the JSON files under `dashboard/grafana/dashboards/`. Grafana reads
them again every 30 seconds, an instance needs no restart for a new link bar.

## Looking further back in the logs

The log list on `/logs` shows the newest 5000 matching lines of the selected
time range (Loki's `max_entries_limit_per_query`). On a busy instance that can
be only a few minutes, so a wider time range alone does not reach older lines.
To look back, drag a range in the volume chart above the list — the list then
shows that period — or narrow it down with Search, Container and Level.

The proxy's access log is hidden by default (filter **Proxy access log**): it
is by far the loudest stream and would use up the 5000 lines within seconds.
Switch it to `shown` when you need the requests themselves.

How far back data exists at all is `DASHBOARD_LOKI_RETENTION`. Queries may span
the whole retention (`max_query_length` follows it), so "This year" no longer
fails with "query time range exceeds the limit".

Odoo's access log lines (`werkzeug`) follow `ODOO_LOG_LEVEL` as well. The
`config_webserver` templates set `werkzeug:DEBUG`, and odoo-bin appends
`--log-handler` to the file's value instead of replacing it, so `run.py` passes
an explicit `werkzeug:<level>` too.
