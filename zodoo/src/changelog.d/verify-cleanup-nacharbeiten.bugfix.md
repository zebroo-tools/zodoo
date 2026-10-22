`odoo pgbackrest verify`: Nacharbeiten zum Aufräumen nach einem Zeitablauf.

- **`restore_timeout` wird geprüft.** Erlaubt sind nur ganze Sekunden größer 0. Bei `"7200"` als Text, `0`, `null` oder `true` fällt die Probe für diesen Bereich sofort mit „restore_timeout … ungueltig“ durch. Bisher gab es dann mitten im Restore einen `TypeError`, einen scheinbaren Zeitablauf oder einen stillen Rückfall auf 3600 s.
- **Der eigentliche Fehler bleibt erhalten.** Scheitert das Entfernen eines Containers oder schon die Suche danach, steht Dockers eigene Meldung in `cleanup_error`, nicht mehr nur „volume is in use“. „No such container“ für bereits entfernte Container ist normal und wird nicht vermerkt.
- **Liegengebliebenes wird gemeldet, solange es da ist.** Nach einem harten Abbruch (SIGKILL, OOM, Neustart) läuft kein Aufräumen. Deshalb sieht jede Probe vorher nach `verify_*`-Volumes, die älter als 12 h sind, und schreibt sie als `leftovers` in den Nachweis. Dazu kommt eine gelbe Zeile nach dem Ergebnis. Gelöscht wird nichts.

Zum Testen auf dem Prüfstand: `docker volume create verify_test_0000000000`. Ab 12 h danach zeigt `odoo pgbackrest verify --bench-config … --stanza <bereich> --json` den Namen unter `leftovers`. Danach `docker volume rm verify_test_0000000000`.
