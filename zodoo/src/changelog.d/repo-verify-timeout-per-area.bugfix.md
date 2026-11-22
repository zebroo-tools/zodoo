`odoo pgbackrest repo-verify --bench-config …` bekommt seine Zeitgrenze jetzt je Bereich aus der Prüfstand-Konfiguration statt fest 4 h. Ein großer Bereich auf einem langsamen Speicher brauchte im November 14003 s und lief eine Woche später in die feste Grenze. Die Prüfung galt dann als beanstandet, obwohl am Bestand nichts fehlte.

Standard bleibt 14400 s. Mehr Zeit für einen Bereich: `"stanzas": {"<bereich>": {"repo_verify_timeout": <sekunden>}}`, je Konfig-Datei, also getrennt für Erst- und Zweitbestand. Der Wert muss eine ganze Zahl > 0 sein; sonst fällt nur dieser Bereich mit „repo_verify_timeout … ungueltig“ durch, ohne dass gelesen wird. `restore_timeout` wird mit derselben Regel geprüft wie bisher.

Zum Testen: auf dem Prüfstand für einen kleinen Bereich `"repo_verify_timeout": 5` setzen und `odoo pgbackrest repo-verify --bench-config … --stanza <bereich>` laufen lassen. Der Bereich fällt mit `TimeoutExpired` durch, die anderen laufen mit 4 h wie bisher.
