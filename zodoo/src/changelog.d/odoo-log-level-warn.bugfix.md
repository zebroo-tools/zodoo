Odoo loggt auf echten Instanzen standardmäßig nur noch Warnungen und Fehler.

Bisher stand in `odoo/default.settings` `ODOO_LOG_LEVEL=debug`, und weil der Wert per Kommandozeile an odoo-bin geht, lief damit jede Instanz ohne eigene Einstellung auf debug. Diese Zeilen landen alle im Loki des Dashboards und machen die Logsuche mühsam, ohne dass sie jemand liest.

Neu: bleibt `ODOO_LOG_LEVEL` leer, setzt zodoo `warn` (DEVMODE=0) bzw. `info` (DEVMODE=1). Ein ausdrücklich gesetzter Wert gilt weiter. `warning` wird zu `warn` umgeschrieben, weil odoo-bin `warning` nicht kennt und sonst nicht startet.

Zum Prüfen: `odoo reload`, dann `odoo setting ODOO_LOG_LEVEL` (zeigt `warn` bzw. `info`); nach `odoo up -d` in `docker top <projekt>_odoo` muss `--log-level=warn` stehen. Wer weiter info sehen will: `odoo setting ODOO_LOG_LEVEL=info`.
