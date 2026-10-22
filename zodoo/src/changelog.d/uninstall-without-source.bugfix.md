A module on the MANIFEST `uninstall` list whose code is no longer in any
addons path no longer crashes `odoo update all` with a `KeyError` after the
services were stopped (#279). `odoo update` now checks this before stopping
anything: it lists the models and fields the uninstall would drop and asks
you to type the module name. Non-interactive runs abort with a clear message
instead, unless the module is listed under the new MANIFEST key
`uninstall_without_source`. Installed modules that still depend on it block
the uninstall in any case. `odoo uninstall <module>` asks the same way.
