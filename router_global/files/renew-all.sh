#!/bin/bash
# No --nginx: every certificate renews with the method it was issued with.
# --nginx would force dns-01 certificates (rfc2136, ionos) onto http-01.
docker-compose exec router certbot renew
