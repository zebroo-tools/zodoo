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

## Access

`/system/` (and with it `/logs`) is behind an access gate in the proxy
(`proxy/lua/dashauth.lua`). The browser editor `/code/` uses the same gate
with its own secrets. There are two ways in:

- **From zCloud, without a password.** The button "Open monitoring" (or "Open
  editor") asks the zCloud backend for a ticket. zCloud checks your session
  and your rights (monitoring: access to the project; editor: the right
  `console`) and signs a ticket that is valid for 60 seconds, only once, only
  for this host and only for this area. The browser POSTs it to
  `/system/__sso` (`/code/__sso`); it never appears in a URL.
- **Directly, with the password.** Without a session the gate shows the
  password page (`DASHBOARD_PASSWORD`, `CODING_PASSWORD`). On non-DEVMODE
  instances the password is generated automatically; `odoo status
  --show-secrets` shows it.

Both lead to the same server-side session: cookie `zodoo_gate_system`
(`zodoo_gate_code`), `Path=/system/` (`/code/`), `HttpOnly`, `SameSite=Lax`,
`Secure`. It ends after 8 hours, or after 2 hours without a request, or with
**Abmelden** in the link bar (`/system/__logout`, `/code/__logout`). Changing
the password or the key ends the sessions made with it. A restart of the proxy
ends all sessions; open it from zCloud again.

What the gate does without credentials: in DEVMODE with neither password nor
key it stays open, as before. On every other instance it answers **503
"Zugang nicht eingerichtet"** instead of showing the dashboard to everyone.

Failed attempts (wrong password, refused ticket) are throttled: after
`GATE_LIMIT_PER_MIN` (10) per minute plus `GATE_LIMIT_BURST` (5) the gate
answers 429. Successful sign-ins do not count.

### Settings (proxy)

| Setting               | Default | Meaning                                                                 |
| --------------------- | ------- | ----------------------------------------------------------------------- |
| `GATE_SSO_KEY_SYSTEM` | empty   | Key for tickets to `/system/`. Empty: no SSO, password only.            |
| `GATE_SSO_KEY_CODE`   | empty   | Same for `/code/`. Its own key, so a monitoring ticket never opens code. |
| `GATE_COOKIE_SECURE`  | empty   | Empty: `Secure` except in DEVMODE. TLS ends at the router in front.      |
| `GATE_SESSION_MAX_S`  | 28800   | Absolute session lifetime (seconds).                                    |
| `GATE_SESSION_IDLE_S` | 7200    | Session ends after this long without a request.                         |
| `GATE_LIMIT_PER_MIN`  | 10      | Failed attempts per minute before 429.                                  |
| `GATE_LIMIT_BURST`    | 5       | Extra failed attempts allowed at once.                                  |

zCloud sets the two keys when it creates or deploys an instance. To switch SSO
off again, set the key empty and `odoo reload && odoo up -d proxy`; the
password keeps working. To rotate, set a new key the same way — tickets and
sessions made with the old one stop working at once.

### Ticket format (for whoever issues tickets)

```
ticket  = base64url(payload) "." base64url(HMAC-SHA256(key, base64url(payload)))
payload = "1|<host>|<area>|<user id>|<iat>|<exp>|<jti>"
```

`<host>` is the instance's host name without port, `<area>` is `/system` or
`/code`, `iat`/`exp` are Unix seconds (at most 300 s apart; the proxy allows
30 s clock skew), `<jti>` is a random id of at least 16 characters. base64url
without padding. The proxy remembers used ids until they expire.

### After updating zodoo

The gate needs a rebuilt proxy image (`odoo reload && odoo build proxy && odoo
up -d proxy`). Until then the proxy keeps the previous password gate, so an
`odoo setup upgrade` alone breaks nothing. Cookies of the previous gate are no
longer accepted; everybody signs in once more.

## The link bar

At the top of both dashboards sits a link bar: **Overview | Logs | Abmelden**. It points
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
