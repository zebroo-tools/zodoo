#!/bin/bash
set -x
set -eux

sed -i "s/__MAIL_SERVER__/$MAIL_SERVER/g" /usr/share/nginx/www/config/config.inc.php && \

# make sure the dirs are there

mkdir -p /rc/logs
mkdir -p /rc/tmp
chown -R www-data:www-data /rc

service nginx start
service php8.4-fpm start

if [[ "$MAIL_AUTOLOGIN" != "1" ]]; then
	rm /usr/share/nginx/www/plugins/autologon/autologon.php || true
fi

tail -F /var/log/nginx/access.log &
tail -F /var/log/nginx/error.log
