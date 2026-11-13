`odoo pgbackrest verify`: „removal of container … is already in progress“ ist kein `cleanup_error` mehr.

Läuft beim Aufräumen gerade das `--rm` eines Probe-Containers, antwortet Docker auf `rm -f` mit dieser Meldung. Der Container ist dann gleich weg; die Probe wurde bisher trotzdem mit einem Aufräum-Vermerk (und gelber Zeile) versehen. Wie „No such container“ wird die Meldung jetzt nicht mehr vermerkt. Andere Fehler beim Entfernen und ein Volume, das nicht weggeht, stehen weiterhin im Nachweis.
