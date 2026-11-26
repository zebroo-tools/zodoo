`odoo reload` nimmt mit `PYTHON_DEPS_EXTRA_MODULES` Module mit, die gleich
installiert werden sollen, aber noch nicht in der Datenbank stehen (z. B. ein
neues Modul aus einem Pull). Deren Python-Pakete und die ihrer `depends` kommen
ins Image, bevor `odoo update` läuft. Prüfen: neues Modul mit
`external_dependencies` ins Repo legen, `odoo reload -cR
"PYTHON_DEPS_EXTRA_MODULES=<modul>"`, `odoo build`, `odoo update <modul>` – das
Paket ist im Container importierbar. Der Wert gilt nur für diesen Reload; ohne
ihn bleibt der requirements.hash wie bisher. Ein Modulname ohne Quellcode im
Addons-Pfad bricht den Reload mit Meldung ab.
