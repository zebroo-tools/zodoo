`odoo status` masks the dashboard password and `DEFAULT_DEV_PASSWORD`. The same
output closes `odoo update` and `odoo up -d`, so both passwords ended up in CI
logs and terminal transcripts of production hosts. `odoo status --show-secrets`
prints them as before.
