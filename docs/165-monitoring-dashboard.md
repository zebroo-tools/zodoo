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
