When the apt cache cannot be started before a build, the warning no longer
claims the build only gets slower: apt-get still uses `APT_PROXY_IP` from
the build settings and fails. It now says so and names the way out
(`odoo setting -s APT_PROXY_IP=ignore && odoo reload`).
