`odoo up` entfernt jetzt alte Container von reinen Build-Services (z.B. `rsync`).

Seit dem Profil `build_only` startet `odoo up -d` den rsync-Container nicht mehr. Ein Container, der vor diesem Update angelegt wurde, blieb aber stehen: compose fasst ihn nicht an, weil der Service noch deklariert ist, und `restart_unhealthy_containers.sh` hat ihn alle paar Minuten neu gestartet, weil der rsync-Entrypoint ohne Argumente mit Exit 1 endet. Aufgefallen auf strack_prod nach dem Update auf 12.10.2.
