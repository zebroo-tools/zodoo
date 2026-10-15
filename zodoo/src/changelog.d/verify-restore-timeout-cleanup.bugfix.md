`odoo pgbackrest verify` räumt nach einem Zeitablauf beim Zurückspielen wieder auf. Bisher lief der Restore-Container nach Ablauf der Stunde namenlos weiter und hielt das Wegwerf-Volume fest; `volume rm` scheiterte, ohne dass es jemand sah. Auf dem Prüfstand sind so sieben Volumes à 22–26 GB liegengeblieben, bis die Platte voll war und keine Probe mehr lief.

Jetzt hat der Restore-Container einen Namen (`verify-<bereich>-<kennung>-restore`), und beim Aufräumen werden vor dem Volume alle Container entfernt, die es noch eingehängt haben. Bleibt trotzdem etwas liegen, steht es im Nachweis als `cleanup_error` und als gelbe Zeile nach dem Ergebnis.

Das Zeitlimit fürs Zurückspielen (Standard 3600 s) lässt sich auf dem Prüfstand je Bereich setzen: `"stanzas": {"<bereich>": {"restore_timeout": <sekunden>}}`.

Zum Testen: auf dem Prüfstand für einen kleinen Bereich `"restore_timeout": 5` setzen und `odoo pgbackrest verify --bench-config … --stanza <bereich>` laufen lassen. Die Probe fällt mit `TimeoutExpired` durch, danach zeigen `docker ps -a` und `docker volume ls | grep verify_` nichts mehr von diesem Lauf.
