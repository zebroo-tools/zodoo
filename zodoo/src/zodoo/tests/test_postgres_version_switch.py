"""POSTGRES_VERSION selects the server Dockerfile and the client in all images.

Background: the client switch in common_snippets/postgres knew 15, 16 and 17
by name and sent everything else to its else branch, which installs
postgresql-client-14. A new server version (19) would therefore have been
paired with client 14 in pgbackrest, cronjobs, pgtools and console without
any error: pg_dump 14 refuses to dump a newer server, so backups would only
fail at runtime.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from zodoo.tools import remove_comments_not_snippets

REPO_ROOT = Path(__file__).resolve().parents[4]
POSTGRES_DIR = REPO_ROOT / "postgres"
SNIPPET = REPO_ROOT / "common_snippets" / "postgres"

# Server versions zodoo ships a Dockerfile for (see docs/070-settings-reference.md).
SUPPORTED = ["11", "12", "13", "14", "16", "17", "19"]


def _load_after_compose():
    spec = importlib.util.spec_from_file_location(
        "postgres_after_compose", POSTGRES_DIR / "__after_compose.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestServerDockerfile:
    def test_default_version_stays_17(self):
        lines = (POSTGRES_DIR / "default.settings").read_text().splitlines()
        assert "POSTGRES_VERSION=17" in lines

    @pytest.mark.parametrize("version", SUPPORTED)
    def test_after_compose_picks_existing_dockerfile(
        self, version, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("HOME", str(tmp_path))  # no ~/.odoo/postgres.conf
        ac = _load_after_compose()
        yml = {
            "services": {
                "postgres": {"build": {"dockerfile": "x"}, "volumes": []}
            },
            "volumes": {},
        }
        settings = {
            "POSTGRES_VERSION": version,
            "NAMED_ODOO_POSTGRES_VOLUME": "",
            "PROJECT_NAME": "p",
        }
        ac.after_compose(None, settings, yml, {})
        dockerfile = yml["services"]["postgres"]["build"]["dockerfile"]
        assert dockerfile == f"Dockerfile.{version}"
        assert (POSTGRES_DIR / dockerfile).is_file()

    def test_dockerfile_19_has_extensions_and_pgbackrest(self):
        content = (POSTGRES_DIR / "Dockerfile.19").read_text()
        assert "FROM postgres:19-" in content
        assert "postgresql-19-postgis-3" in content
        assert "postgresql-19-pgvector" in content
        assert "pgbackrest version" in content
        assert "-17" not in content
        # purging libgdal* takes postgis with it (see Dockerfile.17)
        assert not any(
            "purge" in line and "libgdal" in line
            for line in content.splitlines()
            if not line.lstrip().startswith("#")
        )
        assert "postgis.control" in content


def _client_switch_script():
    """The second RUN of the snippet as a plain shell script.

    The apt_install snippet is replaced by a bare `apt-get install -y`, because
    it reads files under /opt and /etc that only exist in the image.
    """
    lines = remove_comments_not_snippets(SNIPPET.read_text().splitlines())
    text = "\n".join(lines)
    runs = text.split("RUN \\\n")
    assert (
        len(runs) == 3
    ), "expected two RUN blocks in common_snippets/postgres"
    body = runs[2].replace("#___SNIPPET_APT_INSTALL___", "apt-get install -y")
    return body.replace("\\\n", " ")


def _run_switch(tmp_path, postgres_version):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "apt.log"
    stub = bindir / "apt-get"
    stub.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    env["POSTGRES_VERSION"] = postgres_version
    proc = subprocess.run(
        ["sh", "-c", _client_switch_script()],
        env=env,
        capture_output=True,
        text=True,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    installs = [c for c in calls if c.startswith("install")]
    purges = [c for c in calls if c.startswith("purge")]
    return proc, installs, purges


class TestClientSwitch:
    @pytest.mark.parametrize(
        "version,client",
        [
            ("", "14"),
            ("11", "14"),
            ("12", "14"),
            ("13", "14"),
            ("14", "14"),
            ("16", "16"),
            ("17", "17"),
            ("19", "19"),
        ],
    )
    def test_installs_matching_client(self, tmp_path, version, client):
        proc, installs, purges = _run_switch(tmp_path, version)
        assert proc.returncode == 0, proc.stderr
        assert installs == [f"install -y postgresql-client-{client}"]
        if client != "17":
            # the first RUN of the snippet always installs client 17
            assert any("postgresql-client-17" in p for p in purges)

    @pytest.mark.parametrize("version", ["10", "abc", "17.2"])
    def test_unknown_version_fails_instead_of_falling_back(
        self, tmp_path, version
    ):
        proc, installs, _ = _run_switch(tmp_path, version)
        assert proc.returncode != 0
        assert installs == []
        assert "unsupported POSTGRES_VERSION" in proc.stderr
