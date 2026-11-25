`odoo setting KEY VALUE` (ohne `=`) bricht jetzt mit Exit-Code 1 ab und zeigt die richtige Form, z. B. `odoo setting ODOO_DEMO=1`; bisher wurde still nichts geschrieben.
Abbruch gibt es bei Argumenten, die kein Name einer Einstellung sein können (Zahl, true/false/yes/no, Pfad, Sonderzeichen). Lesen mit Teilbegriff (`odoo setting port`) geht weiter, ein Name ohne Treffer meldet `<NAME>: nicht gesetzt`.
Lesen und Schreiben in einem Aufruf (`odoo setting A=1 B`) meldet jetzt verständlich „Cannot mix reading and writing settings.“
