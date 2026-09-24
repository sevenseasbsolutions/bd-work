#!/usr/bin/env bash
# Rolls the latest code out to the running site. Run as root, after setup.sh has run once:
#   sudo bash deploy/update.sh             # pull main from GitHub, then deploy
#   sudo NO_PULL=1 bash deploy/update.sh   # deploy the working tree as it is, no pull
#   sudo FULL=1 bash deploy/update.sh      # rebuild everything, changed or not
#
# It backs the database up, pulls, reinstalls what changed, rebuilds the browser
# app if it changed, and always restarts the API — so edits to backend/.env or
# the Google key file take effect even when there is no new code. backend/.env,
# the key file and the database contents are never touched.
# The schema is brought up to date by the API itself on start (app/schema.py).
set -euo pipefail

DOMAIN=server.idsservices.us
APP=/home/server/bd-work
HERE="$APP/deploy"
USER_=server
NODE_BIN=/home/server/.nvm/versions/node/v24.21.0/bin
BACKUPS=/home/server/bd-work-backups   # outside the repo; last 14 kept
KEEP=14
# The commit that is live. Changes are measured from here, not from before the
# pull, so a commit made on the server itself still counts as new.
STAMP="$APP/.deployed-rev"
NO_PULL="${NO_PULL:-}"
FULL="${FULL:-}"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m    %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mx  %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run this with sudo."
[[ -f "$APP/backend/.env" ]] || die "Missing $APP/backend/.env"
[[ -d "$NODE_BIN" ]] || die "Missing $NODE_BIN (node version changed? update this script and bd-work-web.service)"

# Build steps run as the app user, never root, so nothing in the tree ends up root-owned.
as_app() { sudo -u "$USER_" -H env PATH="$NODE_BIN:/usr/local/bin:/usr/bin:/bin" "$@"; }
git_() { as_app git -C "$APP" "$@"; }

say "Backing the database up"
mkdir -p "$BACKUPS"
chown "$USER_:$USER_" "$BACKUPS"
chmod 700 "$BACKUPS"
DB_NAME=$(grep '^MBS_DATABASE_URL=' "$APP/backend/.env" | sed -E 's#.*/([^/?]+).*#\1#')
DUMP="$BACKUPS/$DB_NAME-$(date +%Y%m%d-%H%M%S).sql.gz"
sudo -u postgres pg_dump "$DB_NAME" | gzip > "$DUMP"
chown "$USER_:$USER_" "$DUMP"
echo "    $DUMP ($(du -h "$DUMP" | cut -f1))"
ls -1t "$BACKUPS"/*.sql.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f

say "Getting the code"
if [[ -n "$NO_PULL" ]]; then
  echo "    NO_PULL set: deploying the working tree as it is."
else
  if [[ -n "$(git_ status --porcelain --untracked-files=no)" ]]; then
    git_ status --short --untracked-files=no
    die "Uncommitted changes in $APP. Commit and push them, or re-run with NO_PULL=1."
  fi
  git_ pull --ff-only
fi
NEW=$(git_ rev-parse HEAD)
OLD=$(cat "$STAMP" 2>/dev/null || true)
if [[ -n "$FULL" || -n "$NO_PULL" || -z "$OLD" ]] || ! git_ cat-file -e "$OLD^{commit}" 2>/dev/null; then
  CHANGED=ALL
  echo "    Rebuilding everything at ${NEW:0:7}."
elif [[ "$OLD" == "$NEW" ]]; then
  CHANGED=
  echo "    No new code since ${NEW:0:7}; restarting only (picks up .env / key changes)."
else
  git_ --no-pager log --oneline "$OLD..$NEW"
  CHANGED=$(git_ diff --name-only "$OLD" "$NEW")
fi
changed() { [[ "$CHANGED" == ALL ]] || grep -qE "$1" <<<"$CHANGED"; }

say "Python dependencies"
if changed '^backend/requirements\.txt$'; then
  as_app "$APP/backend/.venv/bin/pip" install -q -r "$APP/backend/requirements.txt"
else
  echo "    requirements.txt unchanged; skipped."
fi

say "Browser app"
if changed '^frontend/package(-lock)?\.json$' || [[ ! -d "$APP/frontend/node_modules" ]]; then
  # npm ci wipes node_modules, which the running preview server lives in; stop it first.
  systemctl stop bd-work-web
  (cd "$APP/frontend" && as_app npm ci --no-audit --no-fund)
fi
if changed '^frontend/'; then
  # Build beside the live dist/ and swap, so the site is never served half-built.
  (cd "$APP/frontend" && as_app npx vite build --outDir dist.new --emptyOutDir)
  rm -rf "$APP/frontend/dist.old"
  [[ -d "$APP/frontend/dist" ]] && mv "$APP/frontend/dist" "$APP/frontend/dist.old"
  mv "$APP/frontend/dist.new" "$APP/frontend/dist"
  rm -rf "$APP/frontend/dist.old"
else
  echo "    frontend/ unchanged; skipped."
fi

say "systemd units and nginx"
# Always: cheap, and keeps what systemd runs in step with the files in deploy/.
install -m 644 "$HERE/bd-work-api.service" /etc/systemd/system/
install -m 644 "$HERE/bd-work-web.service" /etc/systemd/system/
systemctl daemon-reload
if changed '^deploy/nginx-'; then
  install -m 644 "$HERE/nginx-proxy.inc" /etc/nginx/snippets/bd-work-proxy.conf
  if [[ -f /etc/letsencrypt/live/$DOMAIN/fullchain.pem ]]; then
    install -m 644 "$HERE/nginx-bd-work-ssl.conf" /etc/nginx/sites-available/bd-work
  else
    install -m 644 "$HERE/nginx-bd-work-http.conf" /etc/nginx/sites-available/bd-work
  fi
  nginx -t
  systemctl reload nginx
else
  echo "    nginx config unchanged; skipped."
fi

say "Restarting"
chmod 600 "$APP/backend/.env" "$APP/backend/service-account.json" 2>/dev/null || true
systemctl restart bd-work-api
# vite preview indexes dist/ at start-up, so new hashed assets 404 until it restarts.
# Also brings it back after npm ci stopped it.
if changed '^(frontend/|deploy/bd-work-web\.service$)' || ! systemctl is-active -q bd-work-web; then
  systemctl restart bd-work-web
fi

say "Health check"
ok=
for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 http://127.0.0.1:8010/health >/dev/null 2>&1 \
     && curl -fsS --max-time 2 -o /dev/null http://127.0.0.1:8011/ 2>/dev/null; then
    ok=1; break
  fi
  sleep 1
done
if [[ -z "$ok" ]]; then
  warn "Not healthy after 30s. Recent logs:"
  journalctl -u bd-work-api -u bd-work-web -n 40 --no-pager >&2
  [[ -n "$OLD" ]] && warn "To roll back: sudo -u $USER_ git -C $APP reset --hard ${OLD:0:7} && sudo NO_PULL=1 bash $HERE/update.sh"
  warn "Database backup from just now: $DUMP"
  exit 1
fi
as_app sh -c "echo '$NEW' > '$STAMP'"

echo "    ${NEW:0:7} is live at https://$DOMAIN — tell everyone to reload the page."
