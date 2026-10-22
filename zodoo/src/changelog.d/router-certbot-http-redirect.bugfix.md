The web-router now renders the plain-HTTP redirect for `use_certbot` vhosts
itself instead of leaving it to certbot.

certbot writes that block into the delivered file only, and a re-render
replaces the file while carrying back the TLS directives alone - so the
redirect was lost and the vhost stopped answering on port 80 altogether. On
one router this had reached 17 of 163 vhosts. The block keeps the ACME
challenge path answerable over plain HTTP, so issuing a first certificate
still works.
