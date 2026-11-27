`odoo build` behält die Python-Pakete von Modulen aus der Datenbank und aus
`PYTHON_DEPS_EXTRA_MODULES`. Die Prüfung von `requirements.hash` vor dem Build
hat bisher nur die MANIFEST-install-Liste gezählt. Nach einem `odoo reload -cR
"PYTHON_DEPS_EXTRA_MODULES=<modul>"` hielt sie den Hash darum für veraltet,
führte `odoo reload` ohne das Modul aus, und das Image kam ohne dessen Paket;
`odoo update <modul>` scheiterte dann an der fehlenden Abhängigkeit. Prüfen:
neues Modul mit `external_dependencies` ins Repo legen, `odoo reload -cR
"PYTHON_DEPS_EXTRA_MODULES=<modul>"`, `odoo build` – die Ausgabe meldet keinen
veralteten `requirements.hash`, und nach `odoo update <modul>` ist das Paket im
Container importierbar.
