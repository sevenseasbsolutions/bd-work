#!/usr/bin/env bash
# Pulls the latest main and rolls it out. Run as root, after setup.sh has run once:
#   sudo bash deploy/update.sh
#   sudo NO_PULL=1 bash deploy/update.sh   # redeploy the working tree as it is
# The database schema is brought up to date by the API itself on start
# (app/schema.py), so there is no migration step here.
set -euo pipefail

DOMAIN=server.idsservices.us
APP=/home/server/bd-work
HERE="$APP/deploy"
USER_=server
NODE_BIN=/home/server/.nvm/versions/node/v24.21.0/bin
NO_PULL="${NO_PULL:-}"

[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
[[ -d "$NODE_BIN" ]] || { echo "Missing $NODE_BIN (node version changed? update this script and bd-work-web.service)" >&2; exit 1; }

# Build steps run as the app user, never root, so nothing in the tree ends up root-owned.
as_app() { sudo -u "$USER_" -H env PATH="$NODE_BIN:/usr/local/bin:/usr/bin:/bin" "$@"; }
git_() { as_app git -C "$APP" "$@"; }

echo "== 1. Code"
OLD=$(git_ rev-parse HEAD)
if [[ -n "$NO_PULL" ]]; then
  echo "NO_PULL set: deploying the working tree at ${OLD:0:7} as it is."
  CHANGED=ALL
else
  if [[ -n "$(git_ status --porcelain --untracked-files=no)" ]]; then
    echo "!! Uncommitted changes in $APP. Commit or stash them, or re-run with NO_PULL=1." >&2
    exit 1
  fi
  git_ pull --ff-only
  NEW=$(git_ rev-parse HEAD)
  if [[ "$OLD" == "$NEW" ]]; then
    echo "Already at ${NEW:0:7}; nothing new. Re-run with NO_PULL=1 to force a rebuild."
    exit 0
  fi
  git_ --no-pager log --oneline "$OLD..$NEW"
  CHANGED=$(git_ diff --name-only "$OLD" "$NEW")
fi
changed() { [[ "$CHANGED" == ALL ]] || grep -qE "$1" <<<"$CHANGED"; }

echo "== 2. Backend dependencies"
if changed '^backend/requirements\.txt$'; then
  as_app "$APP/backend/.venv/bin/pip" install -q -r "$APP/backend/requirements.txt"
else
  echo "requirements.txt unchanged; skipped."
fi

echo "== 3. Frontend build"
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
  echo "frontend/ unchanged; skipped."
fi

echo "== 4. systemd units and nginx"
if changed '^deploy/.*\.service$'; then
  install -m 644 "$HERE/bd-work-api.service" /etc/systemd/system/
  install -m 644 "$HERE/bd-work-web.service" /etc/systemd/system/
  systemctl daemon-reload
fi
if changed '^deploy/nginx-'; then
  install -m 644 "$HERE/nginx-proxy.inc" /etc/nginx/snippets/bd-work-proxy.conf
  if [[ -f /etc/letsencrypt/live/$DOMAIN/fullchain.pem ]]; then
    install -m 644 "$HERE/nginx-bd-work-ssl.conf" /etc/nginx/sites-available/bd-work
  else
    install -m 644 "$HERE/nginx-bd-work-http.conf" /etc/nginx/sites-available/bd-work
  fi
  nginx -t
  systemctl reload nginx
fi

echo "== 5. Restart"
if changed '^(backend/|deploy/bd-work-api\.service$)'; then
  systemctl restart bd-work-api
fi
# vite preview indexes dist/ at start-up, so new hashed assets 404 until it restarts.
# Also brings it back after npm ci stopped it.
if changed '^(frontend/|deploy/bd-work-web\.service$)' || ! systemctl is-active -q bd-work-web; then
  systemctl restart bd-work-web
fi

echo "== 6. Health check"
ok=
for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 http://127.0.0.1:8010/health >/dev/null \
     && curl -fsS --max-time 2 -o /dev/null http://127.0.0.1:8011/; then
    ok=1; break
  fi
  sleep 1
done
if [[ -z "$ok" ]]; then
  echo "!! Not healthy after 30s. Recent logs:" >&2
  journalctl -u bd-work-api -u bd-work-web -n 40 --no-pager >&2
  echo "!! To roll back: sudo -u $USER_ git -C $APP reset --hard ${OLD:0:7} && sudo NO_PULL=1 bash $HERE/update.sh" >&2
  exit 1
fi

echo "== Done: $(git_ rev-parse --short HEAD) is live at https://$DOMAIN"
