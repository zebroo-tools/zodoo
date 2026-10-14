Die Logsuche unter `/logs2` öffnet wieder Grafana Explore statt der Übersicht.

Seit Grafana 11 ist Explore Editoren vorbehalten. Hinter dem Passwort-Gate ist jeder ein anonymer Viewer, deshalb leitete Grafana `/logs2` stillschweigend auf das Übersichts-Dashboard um. `GF_USERS_VIEWERS_CAN_EDIT=true` lässt Viewer in Explore; Dashboards speichern können sie weiterhin nicht.

Zum Prüfen: `odoo reload && odoo up -d`, dann `<url>/logs2` öffnen – es muss Explore mit der Loki-Abfrage `{job="docker"}` erscheinen.
