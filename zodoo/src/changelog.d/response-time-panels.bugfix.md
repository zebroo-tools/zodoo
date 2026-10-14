Die Response-Time-Panels im Dashboard (`/system`) zeigen wieder Werte statt „No data".

Die Abfragen lasen das nginx-Accesslog mit einem nackten `| json`. Damit wird jedes Feld zum Label – auch `uri`, `remote_addr` und `time` –, jeder Zugriff wird zu einer eigenen Zeitreihe, und Loki bricht bei 500 Reihen ab („maximum of series (500) reached"). Neu wird nur `request_time` (bei den Routen-Panels zusätzlich `uri`) ausgelesen und zusammengefasst.

Zum Prüfen: `<url>/system` öffnen, Abschnitt „Requests & Response times": „Response time (p50 / p95 / max)" und „Avg response time (5m)" zeigen Werte.
