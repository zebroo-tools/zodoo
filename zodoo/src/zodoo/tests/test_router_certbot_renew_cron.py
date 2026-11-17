"""router_global Dockerfile: the cron job that renews the certificates.

cloud.zebroo.de expired on 2026-10-29 without anybody noticing. The job was
'@monthly certbot renew' in root's crontab: cron runs it with PATH=/usr/bin:/bin,
but certbot is pip-installed to /usr/local/bin, so it would not even have been
found. And with certbot's 30-day window a monthly run leaves no room for a
single failed attempt.

The absolute certbot path was not enough: certbot's nginx authenticator/installer
looks up the 'nginx' binary itself, and that lives in /usr/sbin. With cron's
PATH=/usr/bin:/bin every twice-daily run failed with "Could not find a usable
'nginx' binary" (seen on hy-router, 2026-10-30 until 2026-11-13).
"""

from __future__ import annotations

import re
from pathlib import Path

_DOCKERFILE = (
    Path(__file__).resolve().parents[4] / "router_global" / "files" / "Dockerfile"
)


def _cron_lines():
    """The lines the Dockerfile writes into /etc/cron.d/certbot-renew."""
    text = _DOCKERFILE.read_text()
    match = re.search(r"printf '([^']*)'\s*>\s*/etc/cron\.d/certbot-renew", text)
    assert match, "Dockerfile does not write /etc/cron.d/certbot-renew via printf"
    return [line for line in match.group(1).split(r"\n") if line.strip()]


def _job():
    jobs = [line for line in _cron_lines() if "certbot" in line and "=" not in line]
    assert len(jobs) == 1, jobs
    return jobs[0].split()


def test_runs_at_least_daily():
    minute, hour, dom, month, dow = _job()[:5]
    assert not minute.startswith("@") and minute.isdigit()
    assert (dom, month, dow) == ("*", "*", "*")


def test_certbot_found_without_login_path():
    job = _job()
    assert job[5] == "root", "cron.d lines need the user field"
    assert job[6] == "/usr/local/bin/certbot"


def test_not_installed_as_user_crontab_too():
    # 'crontab /etc/cron.d/...' would read the user field as the command.
    assert not re.search(r"^\s*RUN\s+crontab\b", _DOCKERFILE.read_text(), re.M)


def test_path_contains_sbin_for_nginx_plugin():
    env = dict(
        line.split("=", 1) for line in _cron_lines() if re.match(r"^[A-Z_]+=", line)
    )
    assert "PATH" in env, "cron.d file must set PATH, cron's default lacks /usr/sbin"
    path = env["PATH"].split(":")
    assert "/usr/sbin" in path, "certbot's nginx plugin needs /usr/sbin/nginx"
    assert "/usr/local/bin" in path
