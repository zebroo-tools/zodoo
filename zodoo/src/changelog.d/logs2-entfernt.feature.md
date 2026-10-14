`/logs2` gibt es nicht mehr als eigene Ansicht; die Adresse leitet auf `/logs` um.

`/logs2` öffnete Grafana Explore. Seit Grafana 11 ist Explore Editoren vorbehalten, hinter dem Passwort-Gate ist aber jeder ein anonymer Viewer – Grafana schob `/logs2` deshalb stillschweigend auf das Übersichts-Dashboard. Statt Viewern Bearbeitungsrechte zu geben, bleibt es bei einer Logansicht: `/logs` mit Suche (Regex, ohne Groß-/Kleinschreibung), Container- und Level-Filter.

Zum Prüfen: `odoo reload && odoo up -d proxy`, dann `<url>/logs2` öffnen – man landet auf `/logs`.
