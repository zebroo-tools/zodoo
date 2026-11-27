`odoo build` liest `PYTHON_DEPS_EXTRA_MODULES` jetzt genauso wie `odoo reload`:
Leerzeichen und doppelte Namen fallen weg. Die Doku zum MANIFEST sagt jetzt,
dass `-cR` (zusätzliche Settings nur für diesen Reload) den Wert in die
generierten Run-Settings schreibt, nicht in die Projekt-Settings. Dort sieht
ihn das folgende `odoo build`; er endet mit dem nächsten `odoo reload` ohne
`-cR`. Prüfen: `odoo reload -cR "PYTHON_DEPS_EXTRA_MODULES= mod_a , mod_a"`,
dann `odoo build` – kein Hinweis auf einen veralteten `requirements.hash`.
