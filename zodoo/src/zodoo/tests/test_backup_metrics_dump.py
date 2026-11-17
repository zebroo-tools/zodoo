"""Kennzahlen fuer die naechtliche Dump-Sicherung (art="dump").

Instanzen ohne pgbackrest sichern mit `odoo backup odoo-db`. Bisher stand
ihre Sicherung in der Ueberwachung als "aus", obwohl sie jede Nacht lief.
Geprueft wird vor allem, was NICHT gemeldet werden darf: ein halb
geschriebener Dump, fremde Dateien im Ordner, eine 0 statt einer Luecke.
"""

import os

from zodoo import lib_backup_metrics as bm


class FakeConfig:
    project_name = "kunde"
    run_pgbackrest = "0"
    run_offsite = "0"
    cronjob_backup_daily = "0 0 * * * odoo backup odoo-db x.dump.gz"
    dirs = {}

    def __init__(self, dumps_path):
        self.dumps_path = str(dumps_path)


def _datei(ordner, name, mtime):
    pfad = ordner / name
    pfad.write_bytes(b"PGDMP")
    os.utime(pfad, (mtime, mtime))
    return pfad


def _ausgabe(config, capsys, monkeypatch, tmp_path):
    # Not inside the cronjobs container: the mount path does not exist.
    monkeypatch.setattr(bm, "DUMPS_IM_CONTAINER", str(tmp_path / "gibt-es-nicht"))
    bm.backup_metrics.callback.__wrapped__(config, stdout=True)
    return capsys.readouterr().out


def test_newest_finished_dump_is_reported(tmp_path, capsys, monkeypatch):
    dumps = tmp_path / "dumps"
    dumps.mkdir()
    _datei(dumps, "kunde.odoo.20261115000000.dump.gz", 1794700000)
    _datei(dumps, "kunde.odoo.20261116000000.dump.gz", 1794790000)
    # still being written, a log and a marker: none of them counts
    _datei(dumps, ".kunde.manual.dump.gz", 1794800000)
    _datei(dumps, "kunde.manual.dump.err", 1794800001)
    _datei(dumps, "odoo.files.marker", 1794800002)

    out = _ausgabe(FakeConfig(dumps), capsys, monkeypatch, tmp_path)

    assert 'zodoo_backup_enabled{art="dump"} 1' in out
    assert 'zodoo_backup_query_success{art="dump"} 1' in out
    assert 'zodoo_backup_count{art="dump"} 2' in out
    assert 'zodoo_backup_last_success_timestamp_seconds{art="dump"} 1794790000' in out


def test_no_dump_yet_leaves_the_line_out(tmp_path, capsys, monkeypatch):
    dumps = tmp_path / "dumps"
    dumps.mkdir()
    out = _ausgabe(FakeConfig(dumps), capsys, monkeypatch, tmp_path)
    assert 'zodoo_backup_count{art="dump"} 0' in out
    # a 0 would read as "backed up in 1970"
    assert "zodoo_backup_last_success_timestamp_seconds" not in out


def test_unreadable_folder_is_reported_as_such(tmp_path, capsys, monkeypatch):
    out = _ausgabe(FakeConfig(tmp_path / "fehlt"), capsys, monkeypatch, tmp_path)
    assert 'zodoo_backup_query_success{art="dump"} 0' in out
    assert 'zodoo_backup_count{art="dump"}' not in out


def test_without_daily_cron_dump_is_off(tmp_path, capsys, monkeypatch):
    config = FakeConfig(tmp_path)
    config.cronjob_backup_daily = ""
    out = _ausgabe(config, capsys, monkeypatch, tmp_path)
    assert 'zodoo_backup_enabled{art="dump"} 0' in out
    assert 'art="dump"} 1' not in out


def test_each_family_has_one_help_line(tmp_path, capsys, monkeypatch):
    dumps = tmp_path / "dumps"
    dumps.mkdir()
    _datei(dumps, "kunde.odoo.20261116000000.dump.gz", 1794790000)
    out = _ausgabe(FakeConfig(dumps), capsys, monkeypatch, tmp_path)
    for familie in (
        "zodoo_backup_enabled",
        "zodoo_backup_query_success",
        "zodoo_backup_count",
        "zodoo_backup_last_success_timestamp_seconds",
    ):
        assert out.count(f"# HELP {familie} ") == 1, familie
