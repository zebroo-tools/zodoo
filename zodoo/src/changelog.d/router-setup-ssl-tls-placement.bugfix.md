The web-router no longer ends up in a redirect loop when a vhost gets its
first Let's Encrypt certificate.

`certbot --nginx` put `listen 443 ssl` into the plain-HTTP redirect block
instead of the proxy block, so HTTPS answered with a 301 to itself.
`bin/setup_ssl.py` now only lets certbot issue the certificate
(`certonly`) and writes the TLS lines into the proxy block itself.
