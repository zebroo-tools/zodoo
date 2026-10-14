Der Web-Router legt jetzt immer einen Platzhalter-vHost (`00_default`) an, der
Aufrufe unter unbekanntem Namen mit 404 beantwortet. Bisher machte nginx den
ersten eingelesenen Server-Block zum Standard - und eingelesen wird nach
Dateiname. Eine neue Domain, die alphabetisch vorne landete, bekam damit
unbemerkt allen Verkehr fremder Namen ab, inklusive Aufrufen direkt auf die
IP des Routers. Wer einen eigenen Platzhalter in der `vhosts.yml` stehen hat,
behaelt ihn.
