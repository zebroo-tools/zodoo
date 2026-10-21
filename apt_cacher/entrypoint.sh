#!/bin/sh

# Ensure presence.
mkdir -p /data/squid/cache
mkdir -p /data/squid/log
touch /data/squid/log/access.log
touch /data/squid/log/store.log
touch /data/squid/log/cache.log
# Ensure permissions.
chown proxy:proxy /data/squid/cache
chown root:root   /data/squid/log
chown proxy:proxy /data/squid/log/access.log
chown proxy:proxy /data/squid/log/store.log
chown proxy:proxy /data/squid/log/cache.log

# Drop a pid file left over from the previous run: "docker restart" keeps the
# container filesystem, and squid then refuses to start ("Squid is already
# running"). No squid can be running yet, this script is PID 1.
rm -f /var/run/squid-deb-proxy.pid

# Start the proxy.
/etc/init.d/squid-deb-proxy restart

# Watch the log.
tail -f /var/log/squid-deb-proxy/access.log
