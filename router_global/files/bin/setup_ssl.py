#!/usr/bin/env python3
"""Ensure the SSL block is present in sites-enabled/<domain>.

If the file already has 'listen 443 ssl', do nothing.
Otherwise:
  - If no Let's Encrypt cert exists for the domain yet, request one with
    'certbot certonly --nginx'. That only issues the certificate and leaves
    the vhost file alone.
  - Only an existing cert is reused, so a deploy never renews by accident
    (safe vs rate limits).
  - The TLS directives are then written by this script, right below the
    '# SSL_CERTIFICATE_ANSIBLE' placeholder, i.e. inside the server block that
    proxies to the upstream.

Why not let certbot edit the file ('certbot --nginx' / 'certbot install'):
since the HTTP->HTTPS redirect block sits in front of the proxy block, both
blocks listen on port 80 for the same name and certbot picks the first one.
'listen 443 ssl' then landed in the redirect block, so HTTPS answered with a
301 to itself - an endless redirect loop. That hit every newly issued domain
(quattro-test-machine-3c305b.zebroo.de, 2026-10-15). Placing the lines
ourselves at the placeholder does not depend on certbot's block heuristics.

The lines carry certbot's own '# managed by Certbot' marker: lib_router's
fast restore after a re-render recognises the TLS binding by it.

Files without the placeholder (hand-written vhosts) keep the old behaviour
and go through 'certbot install'.
"""
import inspect
import os
import subprocess
import sys
from pathlib import Path

current_dir = Path(os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))))
project_dir = current_dir.parent

PLACEHOLDER = "# SSL_CERTIFICATE_ANSIBLE"
MARKER = "# managed by Certbot"
# Path of the letsencrypt directory inside the router container.
LE_IN_CONTAINER = "/etc/letsencrypt"


def has_existing_cert(project_dir, domain):
    return (project_dir / "letsencrypt" / "live" / domain).is_dir()


def tls_lines(project_dir, domain):
    """The directives certbot itself would write for this domain."""
    live = "{}/live/{}".format(LE_IN_CONTAINER, domain)
    lines = [
        "listen 443 ssl;",
        "ssl_certificate {}/fullchain.pem;".format(live),
        "ssl_certificate_key {}/privkey.pem;".format(live),
    ]
    # Both files are written by certbot on its first run; an include of a
    # missing file would make 'nginx -t' fail for the whole router.
    le = project_dir / "letsencrypt"
    if (le / "options-ssl-nginx.conf").exists():
        lines.append("include {}/options-ssl-nginx.conf;".format(LE_IN_CONTAINER))
    if (le / "ssl-dhparams.pem").exists():
        lines.append("ssl_dhparam {}/ssl-dhparams.pem;".format(LE_IN_CONTAINER))
    return ["{} {}".format(line, MARKER) for line in lines]


def insert_tls(text, lines):
    """Put the lines below the placeholder; None if there is no placeholder."""
    for line in text.splitlines(keepends=True):
        if line.strip() == PLACEHOLDER:
            indent = line[: len(line) - len(line.lstrip())]
            block = "".join("{}{}\n".format(indent, x) for x in lines)
            head, sep, tail = text.partition(line)
            return head + sep + block + tail
    return None


def certbot(*args):
    subprocess.run(
        ['docker-compose', 'exec', '-T', 'router', 'certbot'] + list(args),
        cwd=project_dir, check=True,
    )


def setup(project_dir, file, domain, run=certbot):
    if not has_existing_cert(project_dir, domain):
        # New domain - request a fresh cert. certonly: issue only, no edit.
        # Without an installer certbot does not reload nginx after a renewal
        # any more, so the reload is stored as deploy hook in the renewal conf.
        run(
            'certonly', '--nginx',
            '-d', domain,
            '--non-interactive',
            '--agree-tos',
            '-m', 'marc@itewimmer.de',  # TODO configurable
            '--deploy-hook', 'nginx -s reload',
        )
    text = file.read_text()
    new = insert_tls(text, tls_lines(project_dir, domain))
    if new is None:
        # No placeholder: let certbot bind the existing cert (no ACME call).
        run('install', '--cert-name', domain, '--nginx', '--non-interactive')
        return
    file.write_text(new)


def main():
    domain_arg = sys.argv[1]
    file = Path("sites-enabled") / domain_arg
    content = file.read_text() if file.exists() else ""

    if "listen 443 ssl" in content:
        sys.exit(0)

    for domain in domain_arg.split(" "):
        domain = domain.strip()
        if not domain:
            continue
        setup(project_dir, file, domain)


if __name__ == "__main__":
    main()
