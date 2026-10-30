FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y nginx nginx-extras autossh net-tools iputils-ping wget curl cron ssl-cert pip

# certbot samt Plugins AUS EINER QUELLE. Vorher kam certbot aus apt und wurde
# durch certbot-dns-ionos (pip) auf 5.x hochgezogen, waehrend die Plugins bei
# der apt-Version 1.21 blieben. Die Folge war kein Versionshinweis, sondern
# ein Abbruch mitten im Ausstellen:
#
#   certbot.errors.Error: Unsupported RSA key length: 1024
#
# Das alte nginx-Plugin legt fuer einen frischen 443-Block einen
# Platzhalter-Schluessel mit 1024 Bit an, und den lehnt die neue
# cryptography-Bibliothek ab. Das Zertifikat war dann zwar geholt, aber nicht
# eingebaut -- der vhost blieb ohne TLS.
#
# Feste Versionen: jeder Router-Build bekommt denselben certbot, den wir
# vorher getestet haben. Erhoehen nur gemeinsam (certbot/nginx/rfc2136
# verlangen gleiche Versionen).
RUN pip install --quiet certbot==5.8.0 certbot-nginx==5.8.0 certbot-dns-rfc2136==5.8.0 certbot-dns-ionos==2024.11.9

ADD run.sh /run.sh
ADD bin/ /usr/local/bin/
RUN chmod a+x /run.sh /usr/local/bin/sync_traefik_certs.py

# Twice a day, as Let's Encrypt recommends: certbot only acts on certificates
# inside its 30-day window, so most runs do nothing. The old '@monthly' left no
# room for one failed attempt (cloud.zebroo.de expired on 2026-10-29). Absolute
# path because cron runs jobs with PATH=/usr/bin:/bin and pip puts certbot into
# /usr/local/bin. Output goes to the container log (docker logs), the details
# stay in /var/log/letsencrypt.
RUN printf 'SHELL=/bin/sh\n17 3,15 * * * root /usr/local/bin/certbot renew --quiet >/proc/1/fd/1 2>&1\n' >/etc/cron.d/certbot-renew \
    && chmod 0644 /etc/cron.d/certbot-renew

CMD ./run.sh
