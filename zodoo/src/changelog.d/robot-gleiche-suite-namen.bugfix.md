`odoo robot run --all` bricht nicht mehr ab, wenn zwei Suiten denselben
Dateinamen haben (etwa `tests/suites/test_mapper/test_mapper.robot` und
`mein_modul/tests/test_mapper.robot`). Solche Suiten legen ihre Ausgabe jetzt
unter ihrem Pfad ab, z. B. `robot-output/mein_modul__tests__test_mapper_p1/`;
Suiten mit eindeutigem Namen behalten `<name>_p1`. Vorher schrieben beide in
denselben Ordner, die zweite überschrieb die Ergebnisse der ersten, und der
Lauf endete mit `shutil.Error: Destination path ... report.html already exists`,
sodass die übrigen Suiten nicht mehr liefen. Prüfen: in einem Projekt mit zwei
gleichnamigen Suiten `odoo robot run --all` ausführen – beide erscheinen unter
`/robot-output` mit eigenem Bericht.
