Die Link-Leiste oben in den Monitoring-Dashboards funktioniert wieder. Ein Klick auf "Logs" landete auf /system/logs und damit auf "Page not found", "Log explorer" genauso auf /system/logs2. Grafana hat die Links in seiner eigenen Navigation unterhalb von /system aufgelöst, statt die Adresse wirklich aufzurufen; jetzt lädt der Browser sie selbst, und die Weiterleitungen des Proxys greifen.

"Log explorer" ist aus der Leiste raus: /logs2 leitet seit dem letzten Umbau nur noch auf /logs um, der Eintrag war also doppelt.

Zum Prüfen: /system öffnen, oben auf "Logs" klicken -> Log-Viewer mit Suchleiste; dort auf "Overview" -> zurück zur Übersicht (ohne Grafana-Kopfzeile).
