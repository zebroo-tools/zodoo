# Selbst gehostete Tools-Runner

Die CI verwendet nach dem Organisationsumzug den isolierten Tools-Pool auf
`githubrunner-hetzner`. Die Organisationsgruppe ist auf die 14 umgezogenen
Tool-Repositories beschränkt. zSYNC behält seine sechs bestehenden Runner;
damit sind alle 15 Repositories in zebroo-tools versorgt.
`Odoo-Ninjas/zync-stable` gehört nicht zum neuen Pool.

Linux-x64-Runner im neuen Pool tragen das eindeutige Label `zebroo-tools`.
Gimera und zodoo verwenden für externe Fork-PRs weiterhin GitHub-hosted Runner.
Ihre internen Jobs bekommen je Job ein eigenes Home-, pipx- und Temp-Verzeichnis.
Bake/Prebuild verlangen auf self-hosted zusätzlich einen separaten Docker-Dienst
(`DOCKER_HOST` und nach Prüfung `ZEBROO_DOCKER_ISOLATED=1`). Es wird kein
Docker-Socket des Hosts in diese Umgebung durchgereicht.

Das Job-Home (`$RUNNER_TEMP/h.*`) räumt der letzte Schritt von Bake und Prebuild
selbst weg (`.github/scripts/cleanup-job-home.sh`, auch nach Fehler oder Abbruch).
Der Runner schafft das nicht allein: Die Postgres-Container legen dort Socket und
Logs mit umgemappter UID ab, die der Runner-Benutzer nicht löschen darf. Deshalb
entfernt das Skript zuerst die Container, die etwas aus diesem Job-Home eingebunden
haben, und löscht die Reste dann über einen kurzlebigen Container am selben
Docker-Dienst. Die Tools-Runner teilen sich diesen Dienst, und der Bake nutzt feste
Projektnamen; deshalb wählt das Skript Container über ihre Mounts aus, nie über den
Projektnamen. Es entfernt nur das eigene Job-Home des Jobs; gelingt das nicht,
erscheint eine Warnung im Log, das Jobergebnis bleibt.

Aktivierung erst nach zweiter Prüfung des Runner-Rollouts in Ticket 5697 und
erfolgreichen Smokejobs. YAML, Runner-Auswahl, Job-Isolation und bestehende Hooks
werden lokal geprüft; Laufzeittests auf dem neuen Pool fehlen bis zur Einrichtung.
Keinen Release oder Versionsverteilungsjob zur bloßen Verifikation auslösen.
Rückweg: die neuen Dienste stoppen, Gruppenfreigabe zurücknehmen und diese
Workflowänderung über einen Revert-PR zurücknehmen. Bestehende zSYNC-Runner
bleiben erhalten.
