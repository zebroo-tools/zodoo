`odoo reload` liest jetzt die installierten Module aus der Projektdatenbank
und nimmt deren Python-Pakete ins Image auf, auch wenn das Modul nicht in der
MANIFEST-Installationsliste steht (z. B. über Apps installiert). Prüfen:
Modul mit `external_dependencies` über Apps installieren, `odoo reload` und
`odoo build` ausführen, das Paket ist im Image. Ohne Datenbank erscheint ein
gelber Hinweis, es gilt dann nur das MANIFEST. Module, deren Quellcode in
keinem Addons-Pfad liegt, werden rot mit Modul- und Datenbankname gemeldet.
Abschalten mit `PYTHON_DEPS_FROM_DB=0`, mehrere Datenbanken über
`PYTHON_DEPS_DBS`.
