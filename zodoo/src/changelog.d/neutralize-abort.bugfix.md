`odoo restore odoo-db --neutralize` (without DEVMODE) and `odoo dev-env
neutralize` now abort on Odoo < 16 and on databases without Odoo instead of
printing a warning and finishing successfully with a copy that is not
neutralized. When the neutralization fails while restoring a `zodoo_bin`
file, the database is renamed to `<db>_not_neutralized` so it cannot be
started under its real name.
