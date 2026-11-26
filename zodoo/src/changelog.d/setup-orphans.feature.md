Neuer Befehl `odoo setup orphans` für Settings gelöschter Projekte in `~/.odoo`.

Ohne Schalter listet er nur auf und ändert nichts: je `settings.<projekt>` den gespeicherten Projektpfad und den Status (present / missing / moved / unknown). Mit `-s <ordner>` (mehrfach möglich, Suchtiefe `--depth`, Standard 2) gilt ein Projekt, dessen Ordner dort unter gleichem Namen liegt, als verschoben.

`--clean` verschiebt nach einer Rückfrage `settings.<projekt>` und `run/<projekt>` der Einträge mit Status missing nach `~/.odoo/.trash/<zeitstempel>/`. Einträge mit present, moved und unknown bleiben liegen; Docker-Container, Volumes und Datenbanken fasst der Befehl nicht an. Zurückholen geht von Hand durch Zurückverschieben. `--purge-trash <tage>` löscht nach einer Rückfrage nur Papierkorb-Ordner, die älter als die angegebenen Tage sind. `odoo -f` überspringt die Rückfragen.

Prüfen:

1. `odoo setup orphans --only-orphans` ausführen. Die Liste erscheint, unter `~/.odoo` ändert sich nichts.
2. `odoo setup orphans --clean` ausführen und die Rückfrage mit `n` beantworten. Es ändert sich nichts. Mit `y` liegen die missing-Einträge danach unter `~/.odoo/.trash/<zeitstempel>/` (Settings-Datei und `run/<projekt>`), alle anderen Einträge stehen unverändert in `~/.odoo`.

Details: Befehlsreferenz, Abschnitt `odoo setup orphans`.
