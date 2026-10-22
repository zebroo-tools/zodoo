{#
  The plain-HTTP side of every vhost that terminates TLS: port 80 answers,
  and it answers with a redirect to HTTPS.

  use_certbot vhosts are included on purpose, even though certbot can write a
  redirect block of its own. That block only ever exists in the DELIVERED
  file, and _reinstall_certbot_tls carries back the TLS directives alone - a
  whole server block must not end up nested inside another one. Every
  re-render therefore dropped it and the vhost silently lost port 80: on
  hy-router 17 of 163 vhosts had no listen-80 block left, among them
  hosting.zebroo.de and ntfy.zebroo.de. Since 2026-10-14 those requests land
  in the catch-all vhost and get a 404. Owning the redirect here makes it
  survive a re-render.

  A vhost without TLS must NOT get this block: its own server block already
  listens on port 80, and a second one for the same name would shadow it.
#}
{% set _redirect_on = (item.ssl_key_is_on_destination is defined and item.ssl_key_is_on_destination) or (item.ssl_server_cert is defined and item.ssl_server_cert) or (item.ssl_self_signed is defined and item.ssl_self_signed) or (item.use_certbot is defined and item.use_certbot) %}
{% if _redirect_on %}
# Redirect plain HTTP to HTTPS for {{ item.server_name }}.
server {
    listen 80;
    server_name  {{ item.server_name }};
{% if item.use_certbot is defined and item.use_certbot %}
    # ACME has to stay answerable over plain HTTP: the HTTP-01 challenge for a
    # certificate that does not exist yet cannot be served over HTTPS, and a
    # 301 would send the validator to a port with no certificate on it.
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
{% endif %}
    location / {
        return 301 https://$host$request_uri;
    }
}
{% endif %}
