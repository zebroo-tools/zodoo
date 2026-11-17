"""Kennzahlen zur Sicherung, damit ein Ausfall auffaellt statt zu warten.

Warum es das braucht: eine Instanz, deren Sicherung nicht laeuft, sieht von
aussen aus wie jede andere. Sie antwortet, die Kurven sind gruen, und der
Unterschied faellt genau einmal auf -- an dem Tag, an dem jemand
wiederherstellen will. Am 29.08.2026 stand auf einer frisch aufgesetzten
Maschine die Anmeldung am Backup-Server auf "wartet auf Freigabe", und es
gab keine einzige Stelle, an der man das gesehen haette.

Geschrieben wird eine Datei fuer den textfile-Collector des node_exporter.
Der liest sie bei jedem Abruf mit, und damit stehen die Werte im lokalen
Prometheus -- und ueber remote_write in der zentralen Ablage.

Bewusst wird NICHT das Alter ausgerechnet, sondern der Zeitpunkt der letzten
Sicherung ausgegeben. Das Alter bildet man mit ``time() - <zeitpunkt>``; so
altert der Wert auch dann weiter, wenn dieser Befehl selbst nicht mehr
laeuft. Eine vorberechnete Alterszahl stuende in dem Fall fuer immer still
auf ihrem letzten Wert und saehe gesund aus.

Genau dagegen steht auch ``zodoo_backup_metrics_written_timestamp_seconds``:
altert dieser Wert, laeuft der Schreiber nicht mehr, und alles andere in der
Datei ist ab da nur noch Erinnerung.

Offsite: hier steht nur, ob es eingeschaltet ist. Einen Zeitpunkt gibt es
nicht -- ``offsite list`` liefert Text fuers Auge, und die Zustandsdatei ist
leer. Eine Null hinzuschreiben waere schlimmer als die Luecke: sie saehe aus
wie eine Messung.
"""

import fnmatch
import json
import os
import subprocess
import time

import click

from .cli import cli, pass_config

DATEINAME = "zodoo-backup.prom"


def _truthy(val):
    return str(val).strip().lower() in ("1", "true", "yes", "on")


# Dateiendungen, die `odoo backup odoo-db` schreibt. Alles andere im Ordner
# (Filestore-Kopien, .err-Protokolle, Marker) ist keine Datenbanksicherung.
DUMP_ENDUNGEN = (".dump.gz", ".dump", ".sql.gz", ".sql", ".zip", ".tar.gz", ".tar")

# Inside the cronjobs container the dump folder is mounted here
# (cronjobs/docker-compose.yml); DUMPS_PATH itself is the path on the host.
DUMPS_IM_CONTAINER = "/host/dumps"


def _dump_ordner(config):
    from pathlib import Path

    im_container = Path(DUMPS_IM_CONTAINER)
    if im_container.is_dir():
        return im_container
    pfad = getattr(config, "dumps_path", "") or ""
    return Path(pfad) if pfad else None


def _dump_muster(config):
    """Dateimuster der eigenen Dumps (DB_ODOO_SEARCHFORMAT), oder None.

    Der Dump-Ordner (Default ~/odoo_dumps) ist oft der aller Projekte eines
    Benutzers. Ohne Muster zaehlte der frische Dump eines anderen Projekts
    als eigene Sicherung und verdeckte, dass die eigene seit Tagen fehlt
    (Review 17.11.2026). Dieselben Muster nutzen die Aufraeum-Jobs.

    The pattern must match DB_ODOO_FILEFORMAT: whoever changes the file
    name there has to change DB_ODOO_SEARCHFORMAT too, otherwise no dump
    is found and the state shows "none". Only {project_name} is replaced
    here; other placeholders ({customs}, $VAR) are not supported.
    Dumps of type "directory" (a folder instead of a file) are not counted.
    """
    muster = str(getattr(config, "db_odoo_searchformat", "") or "").strip()
    if not muster:
        return None
    projekt = str(getattr(config, "project_name", "") or "")
    return muster.replace("{project_name}", projekt)


def _dump_werte(config):
    """(lesbar, neueste, anzahl) der Dump-Dateien im Sicherungsordner.

    Viele Instanzen sichern nicht mit pgbackrest, sondern mit dem naechtlichen
    `odoo backup odoo-db` (CRONJOB_BACKUP_DAILY). Ohne diese Zahlen stand ihre
    Sicherung in der Ueberwachung als "aus", obwohl sie jede Nacht lief
    (adoptierte Maschine, 16.11.2026).

    Gezaehlt wird nur, was fertig ist: waehrend des Schreibens liegt der Dump
    unter einem Namen mit fuehrendem Punkt und wird erst am Ende umbenannt.
    Zeitpunkt ist das Aenderungsdatum der neuesten Datei -- also das Ende
    der juengsten Sicherung.
    """
    ordner = _dump_ordner(config)
    if ordner is None:
        return False, None, 0
    muster = _dump_muster(config)
    try:
        dateien = [
            d
            for d in ordner.iterdir()
            if d.is_file()
            and not d.name.startswith(".")
            and (
                fnmatch.fnmatchcase(d.name, muster)
                if muster
                else d.name.endswith(DUMP_ENDUNGEN)
            )
        ]
    except OSError as fehler:
        click.secho(f"Sicherungsordner nicht lesbar: {fehler}", fg="yellow")
        return False, None, 0
    if not dateien:
        return True, None, 0
    neueste = max(int(d.stat().st_mtime) for d in dateien)
    return True, neueste, len(dateien)


def _zeile(name, wert, labels=None):
    if labels:
        teile = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{teile}}} {wert}"
    return f"{name} {wert}"


def _pgbackrest_werte(config):
    """(erfolg, neueste, neueste_voll, anzahl) aus `pgbackrest info`."""
    from .lib_pgbackrest import _pgbr_capture

    try:
        roh = _pgbr_capture(config, ["--output", "json", "info"])
    except (subprocess.CalledProcessError, OSError) as fehler:
        click.secho(f"pgbackrest info fehlgeschlagen: {fehler}", fg="yellow")
        return False, None, None, 0
    try:
        daten = json.loads(roh)
    except json.JSONDecodeError:
        click.secho("pgbackrest info lieferte kein gueltiges JSON", fg="yellow")
        return False, None, None, 0

    neueste = None
    neueste_voll = None
    anzahl = 0
    for stanza in daten:
        for sicherung in stanza.get("backup", []):
            stop = (sicherung.get("timestamp") or {}).get("stop")
            if not stop:
                continue
            anzahl += 1
            if neueste is None or stop > neueste:
                neueste = stop
            if sicherung.get("type") == "full":
                if neueste_voll is None or stop > neueste_voll:
                    neueste_voll = stop
    return True, neueste, neueste_voll, anzahl


def _archiv_werte(config):
    """Zustand der WAL-ARCHIVIERUNG, aus Sicht der Instanz.

    Die Kennzahlen darueber beschreiben SICHERUNGEN. Das ist eine andere
    Frage: eine Instanz kann taeglich sichern und trotzdem seit Tagen kein
    WAL mehr loswerden - dann gibt es zwar Basisstaende, aber keinen
    lueckenlosen Weg dazwischen, und Wiederherstellung auf einen Zeitpunkt
    ist nicht mehr moeglich.

    Gibt None zurueck, wenn sich nichts lesen laesst. Keine Nullen: eine 0
    bei `failed` saehe aus wie "alles gut".
    """
    from .tools import __dc_out

    sql = (
        "SELECT archived_count, failed_count, "
        "coalesce(extract(epoch from last_archived_time)::bigint, 0), "
        "coalesce(extract(epoch from last_failed_time)::bigint, 0) "
        "FROM pg_stat_archiver"
    )
    try:
        roh = __dc_out(
            config,
            ["exec", "-T", "postgres", "psql", "-U", "postgres",
             "-d", "postgres", "-tAc", sql],
        )
    except (subprocess.CalledProcessError, OSError) as fehler:
        click.secho(f"pg_stat_archiver nicht lesbar: {fehler}", fg="yellow")
        return None
    teile = roh.strip().split("|")
    if len(teile) != 4:
        return None
    try:
        return {
            "archiviert": int(teile[0]),
            "gescheitert": int(teile[1]),
            "zuletzt_archiviert": int(teile[2]),
            "zuletzt_gescheitert": int(teile[3]),
        }
    except ValueError:
        return None


def _spool_and_dropped(config):
    """(warteschlange, verworfen) aus dem Sidecar.

    warteschlange: WAL-Segmente, die noch im Spool liegen. Waechst der Wert,
    kommt die Archivierung nicht hinterher oder das Repository ist weg.

    verworfen: wie oft pgBackRest WAL WEGGEWORFEN hat, weil
    `archive-push-queue-max` ueberschritten war. Das ist der gefaehrlichste
    Zustand im ganzen Aufbau: pgBackRest meldet postgres in dem Fall ERFOLG,
    postgres gibt das Segment frei, und danach laeuft alles weiter und sieht
    frisch aus - die Luecke faellt erst beim Wiederherstellen auf. Der
    Kompromiss ist bewusst so gewaehlt (sonst laeuft die Instanzplatte voll),
    aber er darf nicht unbemerkt bleiben.

    Der Zaehler kommt aus dem Logfile und faellt bei dessen Rotation zurueck.
    Als Prometheus-Counter ist das in Ordnung - ein Ruecksetzer wird erkannt;
    was zaehlt, ist der Anstieg.
    """
    from .tools import __dc_out
    from .lib_pgbackrest import _stanza

    stanza = _stanza(config)
    befehl = (
        f"ls -1 /var/spool/pgbackrest/archive/{stanza}/out 2>/dev/null | wc -l;"
        f" grep -c 'dropped WAL file' /var/log/pgbackrest/*.log 2>/dev/null"
        f" | awk -F: '{{s+=$NF}} END {{print s+0}}'"
    )
    try:
        roh = __dc_out(
            config, ["exec", "-T", "pgbackrest", "sh", "-c", befehl]
        )
    except (subprocess.CalledProcessError, OSError) as fehler:
        click.secho(f"Spool nicht lesbar: {fehler}", fg="yellow")
        return None, None
    zeilen = [z.strip() for z in roh.strip().splitlines() if z.strip()]
    if len(zeilen) < 2:
        return None, None
    try:
        return int(zeilen[0]), int(zeilen[1])
    except ValueError:
        return None, None


def _check_zustand(config):
    """Ergebnis des letzten `odoo pgbackrest check`, oder None.

    Der Check ist die einzige Pruefung, die den GANZEN Weg von der Instanz
    aus geht: er schaltet ein WAL-Segment weiter und sieht nach, ob es im
    Repository ankommt. Er laeuft stuendlich per Zeitplan und legt sein
    Ergebnis ab; hier wird es nur gelesen, damit diese Kennzahlen guenstig
    bleiben.
    """
    run_dir = config.dirs.get("run")
    if not run_dir:
        return None
    try:
        with open(run_dir / "pgbackrest-check.json") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


@cli.command(
    name="backup-metrics",
    help=(
        "Kennzahlen zur Sicherung fuer den textfile-Collector schreiben. "
        "Laeuft aus den Cronjobs; von Hand nuetzlich, um zu sehen, was die "
        "Ueberwachung ueber diese Instanz erfaehrt."
    ),
)
@click.option(
    "--stdout",
    is_flag=True,
    help="Nur ausgeben, nichts schreiben.",
)
@pass_config
def backup_metrics(config, stdout):
    pgbr_an = _truthy(getattr(config, "run_pgbackrest", "0"))
    offsite_an = _truthy(getattr(config, "run_offsite", "0"))
    dump_an = bool(str(getattr(config, "cronjob_backup_daily", "") or "").strip())

    zeilen = [
        "# HELP zodoo_backup_enabled Ist diese Sicherungsart eingeschaltet.",
        "# TYPE zodoo_backup_enabled gauge",
        _zeile("zodoo_backup_enabled", int(pgbr_an), {"art": "pgbackrest"}),
        _zeile("zodoo_backup_enabled", int(offsite_an), {"art": "offsite"}),
        _zeile("zodoo_backup_enabled", int(dump_an), {"art": "dump"}),
    ]
    # Samples per metric family, written once at the end: the text format
    # allows HELP/TYPE only once per family, and pgbackrest and dump both
    # report a count and a last success.
    abfragen = []
    anzahlen = []
    letzte = []

    if pgbr_an:
        erfolg, neueste, neueste_voll, anzahl = _pgbackrest_werte(config)
        abfragen.append(
            _zeile("zodoo_backup_query_success", int(erfolg), {"art": "pgbackrest"})
        )
        if erfolg:
            anzahlen.append(_zeile("zodoo_backup_count", anzahl, {"art": "pgbackrest"}))
            # Fehlt eine Sicherung, wird die Zeile WEGGELASSEN statt auf 0
            # gesetzt. Eine 0 hiesse "1970 gesichert" und ergaebe ein
            # gigantisches Alter -- richtig gelesen, aber jeder Schwellenwert
            # wuerde sie mit einer echten alten Sicherung verwechseln. Fehlt
            # sie, faellt in PromQL `absent()` darauf an, und das ist die
            # ehrlichere Frage: es gibt gar keine.
            if neueste:
                letzte.append(
                    _zeile(
                        "zodoo_backup_last_success_timestamp_seconds",
                        neueste,
                        {"art": "pgbackrest"},
                    )
                )
            if neueste_voll:
                zeilen += [
                    "# HELP zodoo_backup_last_full_timestamp_seconds "
                    "Ende der juengsten VOLLstaendigen Sicherung.",
                    "# TYPE zodoo_backup_last_full_timestamp_seconds gauge",
                    _zeile(
                        "zodoo_backup_last_full_timestamp_seconds",
                        neueste_voll,
                        {"art": "pgbackrest"},
                    ),
                ]

        # --- WAL-Archivierung -------------------------------------------
        #
        # Bewusst getrennt von den Sicherungszahlen oben: eine Instanz kann
        # taeglich sichern und trotzdem seit Tagen kein WAL mehr loswerden.
        # Dann gibt es Basisstaende, aber keinen lueckenlosen Weg dazwischen.
        archiv = _archiv_werte(config)
        if archiv is not None:
            zeilen += [
                "# HELP zodoo_wal_archived_total Erfolgreich archivierte "
                "WAL-Segmente seit dem letzten Zuruecksetzen der Statistik.",
                "# TYPE zodoo_wal_archived_total counter",
                _zeile("zodoo_wal_archived_total", archiv["archiviert"]),
                "# HELP zodoo_wal_failed_total Fehlgeschlagene Versuche. "
                "Steigt der Wert, kommt das WAL nicht weg.",
                "# TYPE zodoo_wal_failed_total counter",
                _zeile("zodoo_wal_failed_total", archiv["gescheitert"]),
            ]
            if archiv["zuletzt_archiviert"]:
                zeilen += [
                    "# HELP zodoo_wal_last_archived_timestamp_seconds Wann "
                    "zuletzt ein Segment ankam (Alter: time() - Wert).",
                    "# TYPE zodoo_wal_last_archived_timestamp_seconds gauge",
                    _zeile(
                        "zodoo_wal_last_archived_timestamp_seconds",
                        archiv["zuletzt_archiviert"],
                    ),
                ]
            if archiv["zuletzt_gescheitert"]:
                zeilen += [
                    "# HELP zodoo_wal_last_failed_timestamp_seconds Wann "
                    "zuletzt ein Versuch scheiterte.",
                    "# TYPE zodoo_wal_last_failed_timestamp_seconds gauge",
                    _zeile(
                        "zodoo_wal_last_failed_timestamp_seconds",
                        archiv["zuletzt_gescheitert"],
                    ),
                ]

        warteschlange, verworfen = _spool_and_dropped(config)
        if warteschlange is not None:
            zeilen += [
                "# HELP zodoo_wal_spool_files Wartende WAL-Segmente im Spool. "
                "Waechst der Wert, kommt die Archivierung nicht hinterher.",
                "# TYPE zodoo_wal_spool_files gauge",
                _zeile("zodoo_wal_spool_files", warteschlange),
            ]
        if verworfen is not None:
            zeilen += [
                "# HELP zodoo_wal_dropped_total WAL-Segmente, die pgBackRest "
                "WEGGEWORFEN hat, weil archive-push-queue-max ueberschritten "
                "war. postgres bekommt dabei Erfolg gemeldet - die Luecke "
                "faellt sonst erst beim Wiederherstellen auf. Jeder Anstieg "
                "ist ein Zwischenfall.",
                "# TYPE zodoo_wal_dropped_total counter",
                _zeile("zodoo_wal_dropped_total", verworfen),
            ]

        # --- Ende-zu-Ende-Check -----------------------------------------
        check = _check_zustand(config)
        if check is not None:
            zeilen += [
                "# HELP zodoo_backup_check_success Ergebnis des letzten "
                "`pgbackrest check`: schaltet ein WAL-Segment weiter und "
                "sieht nach, ob es im Repository ankommt.",
                "# TYPE zodoo_backup_check_success gauge",
                _zeile("zodoo_backup_check_success", int(bool(check.get("ok")))),
            ]
            if check.get("at"):
                zeilen += [
                    "# HELP zodoo_backup_check_timestamp_seconds Wann der "
                    "Check zuletzt lief. Altert der Wert, laeuft er nicht "
                    "mehr - und das Ergebnis darueber ist Erinnerung.",
                    "# TYPE zodoo_backup_check_timestamp_seconds gauge",
                    _zeile(
                        "zodoo_backup_check_timestamp_seconds",
                        int(check["at"]),
                    ),
                ]

    if dump_an:
        lesbar, neueste_dump, anzahl_dump = _dump_werte(config)
        abfragen.append(
            _zeile("zodoo_backup_query_success", int(lesbar), {"art": "dump"})
        )
        if lesbar:
            anzahlen.append(_zeile("zodoo_backup_count", anzahl_dump, {"art": "dump"}))
            # Keine Datei: Zeile weglassen statt 0 (siehe oben, pgbackrest).
            if neueste_dump:
                letzte.append(
                    _zeile(
                        "zodoo_backup_last_success_timestamp_seconds",
                        neueste_dump,
                        {"art": "dump"},
                    )
                )

    if abfragen:
        zeilen += [
            "# HELP zodoo_backup_query_success Liess sich der Zustand lesen.",
            "# TYPE zodoo_backup_query_success gauge",
        ] + abfragen
    if anzahlen:
        zeilen += [
            "# HELP zodoo_backup_count Anzahl der Sicherungen.",
            "# TYPE zodoo_backup_count gauge",
        ] + anzahlen
    if letzte:
        zeilen += [
            "# HELP zodoo_backup_last_success_timestamp_seconds "
            "Ende der juengsten Sicherung (Alter: time() - Wert).",
            "# TYPE zodoo_backup_last_success_timestamp_seconds gauge",
        ] + letzte

    zeilen += [
        "# HELP zodoo_backup_metrics_written_timestamp_seconds Wann diese "
        "Datei zuletzt geschrieben wurde. Altert der Wert, laeuft der "
        "Schreiber nicht mehr und alles darueber ist veraltet.",
        "# TYPE zodoo_backup_metrics_written_timestamp_seconds gauge",
        _zeile(
            "zodoo_backup_metrics_written_timestamp_seconds", int(time.time())
        ),
    ]
    text = "\n".join(zeilen) + "\n"

    if stdout:
        click.echo(text)
        return

    run_dir = config.dirs.get("run")
    if not run_dir:
        click.secho(
            "Kein Laufverzeichnis bekannt -- nichts geschrieben.", fg="yellow"
        )
        return
    ordner = run_dir / "dashboard" / "textfile"
    ordner.mkdir(parents=True, exist_ok=True)
    ziel = ordner / DATEINAME

    # Erst daneben, dann umbenennen: der node_exporter liest die Datei bei
    # jedem Abruf und darf sie nie halb beschrieben vorfinden. Die Endung
    # ist wichtig -- der Collector nimmt nur *.prom, die Nebendatei sieht er
    # also gar nicht erst.
    neben = ordner / (DATEINAME + ".neu")
    neben.write_text(text)
    neben.chmod(0o644)
    os.replace(neben, ziel)
    click.secho(f"Sicherungs-Kennzahlen geschrieben: {ziel}", fg="green")
