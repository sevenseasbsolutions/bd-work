#!/usr/bin/env bash
# Deploys bd-work behind nginx at server.idsservices.us. Run as root:
#   sudo bash deploy/setup.sh
#   sudo CERT_EMAIL=you@example.com bash deploy/setup.sh   # expiry notices
# Safe to re-run. Leaves the existing bd-dispatch site untouched.
set -euo pipefail

DOMAIN=server.idsservices.us
APP=/home/server/bd-work
HERE="$APP/deploy"
CERT_EMAIL="${CERT_EMAIL:-}"

[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
[[ -f "$APP/backend/.env" ]] || { echo "Missing $APP/backend/.env" >&2; exit 1; }

echo "== 1. PostgreSQL role and database"
DB_URL=$(grep '^MBS_DATABASE_URL=' "$APP/backend/.env" | cut -d= -f2-)
DB_PW=$(sed -E 's#^[^:]+://[^:]+:([^@]+)@.*#\1#' <<<"$DB_URL")
sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bdwork') THEN
    CREATE ROLE bdwork LOGIN PASSWORD '$DB_PW';
  ELSE
    ALTER ROLE bdwork PASSWORD '$DB_PW';
  END IF;
END \$\$;
SQL
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='bdwork'" | grep -q 1 \
  || sudo -u postgres createdb -O bdwork bdwork

echo "== 2. systemd services"
install -m 644 "$HERE/bd-work-api.service" /etc/systemd/system/
install -m 644 "$HERE/bd-work-web.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable bd-work-api bd-work-web
systemctl restart bd-work-api bd-work-web

echo "== 3. nginx (http)"
mkdir -p /var/www/letsencrypt
install -m 644 "$HERE/nginx-proxy.inc" /etc/nginx/snippets/bd-work-proxy.conf
if [[ -f /etc/letsencrypt/live/$DOMAIN/fullchain.pem ]]; then
  install -m 644 "$HERE/nginx-bd-work-ssl.conf" /etc/nginx/sites-available/bd-work
else
  install -m 644 "$HERE/nginx-bd-work-http.conf" /etc/nginx/sites-available/bd-work
fi
ln -sf /etc/nginx/sites-available/bd-work /etc/nginx/sites-enabled/bd-work
nginx -t
systemctl reload nginx

echo "== 4. Let's Encrypt certificate"
PUBLIC_IP=$(curl -s -4 --max-time 5 https://ifconfig.me || true)
DNS_IP=$(getent ahostsv4 "$DOMAIN" | awk 'NR==1{print $1}' || true)
if [[ -z "$DNS_IP" ]]; then
  echo "!! $DOMAIN has no DNS A record. Point it at $PUBLIC_IP, then re-run this script."
  exit 0
fi
[[ "$DNS_IP" != "$PUBLIC_IP" ]] && echo "!! Warning: $DOMAIN -> $DNS_IP, this server is $PUBLIC_IP. Trying anyway."

certbot certonly --webroot -w /var/www/letsencrypt -d "$DOMAIN" \
  $([[ -n "$CERT_EMAIL" ]] && echo "--email $CERT_EMAIL" || echo "--register-unsafely-without-email") \
  --agree-tos --non-interactive --keep-until-expiring \
  --deploy-hook "systemctl reload nginx"

install -m 644 "$HERE/nginx-bd-work-ssl.conf" /etc/nginx/sites-available/bd-work
nginx -t
systemctl reload nginx
certbot renew --dry-run --cert-name "$DOMAIN" || echo "!! Renewal dry-run failed; check port 80 reachability."

echo "== Done: https://$DOMAIN"
