# TODO: COPY apt mirror
FROM    debian:trixie
ENV     DEBIAN_FRONTEND=noninteractive
ENV     TERM=xterm
ENV     ROUNDCUBE_VERSION=1.6.20
ENV     MAIL_SERVER=mail

#___SNIPPET_APT_PROXY___

WORKDIR /root
RUN mkdir -p /rc
RUN #___SNIPPET_APT_INSTALL___ \
php-net-ldap2 php-net-ldap3 php-imagick php8.4-common php8.4-gd php8.4-ldap php8.4-curl php8.4-zip php8.4-xml php8.4-mbstring php8.4-bz2 php8.4-intl php8.4-gmp php8.4-fpm php8.4-sqlite3
RUN #___SNIPPET_APT_INSTALL___ \
nginx wget ca-certificates composer

RUN ln -sf /dev/stdout /var/log/nginx/access.log && ln -sf /dev/stderr /var/log/nginx/error.log

RUN rm -fr /usr/share/nginx/www && \
wget --progress=dot:giga https://github.com/roundcube/roundcubemail/releases/download/$ROUNDCUBE_VERSION/roundcubemail-${ROUNDCUBE_VERSION}-complete.tar.gz -O - | tar xz && \
mv /root/roundcubemail-$ROUNDCUBE_VERSION /usr/share/nginx/www  && \
rm -Rf /usr/share/nginx/www/installer

WORKDIR /usr/share/nginx/www
RUN composer install --no-dev

COPY config.inc.php /usr/share/nginx/www/config/
COPY default /etc/nginx/sites-enabled/default
COPY launch.sh /root/
COPY php-fpm.ini /etc/php/8.4/fpm/php.ini
RUN nginx -c /etc/nginx/nginx.conf -t

COPY autologon.php /usr/share/nginx/www/plugins/autologon/autologon.php
CMD [ "bash", "/root/launch.sh" ]
