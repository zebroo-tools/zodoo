"""stderr handling of the backup in cronjobs/bin/postgres.py.

Background: since zodoo v11.2.1 the postgres images are built on bookworm
(glibc 2.36). Databases created under bullseye (glibc 2.31) then print a
"collation version mismatch" warning on every connection. The backup treated
any stderr as fatal, so on 14./15.10.2026 odooprod-zebroodo produced no nightly
dump after its postgres container had been rebuilt - while pg_dump itself
exited 0 with a complete dump.
"""

import importlib.machinery
import importlib.util
import logging
import sys
import types
from pathlib import Path

import pytest

POSTGRES_PY = (
    Path(__file__).resolve().parents[4] / "cronjobs" / "bin" / "postgres.py"
)

# verbatim from odooprod-zebroodo, 15.10.2026
REAL_WARNING = (
    'WARNING:  database "zebroodo" has a collation version mismatch\n'
    "DETAIL:  The database was created using collation version 2.31, but the "
    "operating system provides version 2.36.\n"
    "HINT:  Rebuild all objects in this database that use the default collation "
    "and run ALTER DATABASE zebroodo REFRESH COLLATION VERSION, or build "
    "PostgreSQL with the right library version.\n"
)


@pytest.fixture(scope="module")
def modul():
    """Load postgres.py without needing psycopg2/humanize on the test host."""
    for name in ("psycopg2", "humanize"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    spec = importlib.util.spec_from_loader(
        "cronpostgres",
        importlib.machinery.SourceFileLoader("cronpostgres", str(POSTGRES_PY)),
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_collation_warning_alone_does_not_fail_the_backup(modul, caplog):
    with caplog.at_level(logging.WARNING):
        assert modul.split_known_warnings(REAL_WARNING) == ""
    assert any(
        "REFRESH COLLATION VERSION" in r.getMessage() for r in caplog.records
    )


def test_warning_repeated_per_connection_is_logged_once(modul, caplog):
    with caplog.at_level(logging.WARNING):
        modul.split_known_warnings(REAL_WARNING * 3)
    assert (
        len([r for r in caplog.records if "collation" in r.getMessage()]) == 1
    )


def test_real_error_next_to_the_warning_still_fails(modul):
    error = (
        "pg_dump: error: query failed: ERROR:  permission denied for table x"
    )
    assert modul.split_known_warnings(REAL_WARNING + error + "\n") == error


@pytest.mark.parametrize(
    "stderr",
    [
        "pg_dump: error: connection to server failed",
        "WARNING:  some other warning",
        "DETAIL:  detail without the collation warning",
        "gzip: stdout: No space left on device",
    ],
)
def test_other_output_stays_fatal(modul, stderr):
    assert modul.split_known_warnings(stderr + "\n") == stderr


def test_empty_stderr(modul):
    assert modul.split_known_warnings("") == ""
