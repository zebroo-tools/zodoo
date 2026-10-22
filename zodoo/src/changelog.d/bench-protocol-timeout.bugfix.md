`odoo pgbackrest repo-verify` / `verify` mit `--bench-config`: Die Bestandsprüfung großer Bereiche bricht nicht mehr nach 31 Minuten ab.

- **Ursache:** Während `pgbackrest verify` die Sicherungen liest, ruht die Verbindung des Hauptprozesses zum Repo-Host. Nach dem pgBackRest-Standard (1830 s) gibt der Repo-Host auf („timeout after 1860000ms waiting for read“), auf dem Prüfstand steht dann nur „TLS error … unexpected eof while reading“. So ist die Bestandsprüfung von powerhouse_cicd am 11. und 18.10.2026 abgebrochen.
- **Jetzt:** Die pgbackrest.conf des Prüfstands bekommt `protocol-timeout=10800` (3 h). Je Bereich lässt sich das in `stanzas` als `protocol_timeout` (Sekunden) überschreiben. Erlaubt sind ganze Sekunden größer 1800, weil pgBackRest mehr als `db-timeout` verlangt. Sonst fällt der Bereich sofort mit „protocol_timeout … ungueltig“ durch.

Zum Testen auf dem Prüfstand: `odoo pgbackrest repo-verify --bench-config /etc/pgbr-bench/config.json --stanza powerhouse_cicd`. Erwartet wird „Bestand heil“ statt eines TLS-Fehlers nach rund 31 Minuten.
