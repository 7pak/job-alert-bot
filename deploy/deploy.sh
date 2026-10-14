#!/usr/bin/env bash
# Push the code and your config files to a Linux server, then restart the bot.
# Run from anywhere (Git Bash works on Windows):
#   bash deploy/deploy.sh                  # code + config.yml, profile.yml, companies.yml (normal update)
#   bash deploy/deploy.sh --with-secrets   # also copy .env (first deploy, or a new token)
#   bash deploy/deploy.sh --with-db        # also copy data/jobs.db (first deploy only; stop the local bot first)
#   bash deploy/deploy.sh --with-cv        # also copy your CV (only if CV tailoring is on)
#
# Settings come from environment variables or deploy/.deploy.env (gitignored, see .deploy.env.example):
#   JOBBOT_HOST     user@server (required)
#   JOBBOT_KEY      ssh private key (optional, default: your ssh config)
#   JOBBOT_APP_DIR  install folder on the server (default /opt/job-alert-bot)
#   JOBBOT_SERVICE  systemd service name (default job-alert-bot)
#   JOBBOT_USER     system user that runs the bot (default jobbot)
#   JOBBOT_EXTRAS   extra pip packages for the server (default: worked out from config.yml, e.g. the
#                   anthropic SDK and python-docx when CV tailoring is on). Set to "none" for none.
# The server needs a one-time `sudo bash deploy/setup_server.sh` first (see docs/deployment.md).
set -euo pipefail
cd "$(dirname "$0")/.."

# deploy/.deploy.env fills in only what the environment does not already set.
if [ -f deploy/.deploy.env ]; then
  while IFS='=' read -r k v; do
    k="${k//[[:space:]]/}"
    case "$k" in ''|\#*) continue ;; esac
    v="${v%%#*}"; v="${v%"${v##*[![:space:]]}"}"; v="${v#\"}"; v="${v%\"}"
    if [ -z "${!k:-}" ]; then export "$k=$v"; fi
  done < deploy/.deploy.env
fi

HOST="${JOBBOT_HOST:?Set JOBBOT_HOST=user@server in deploy/.deploy.env or the environment}"
KEY="${JOBBOT_KEY:-}"
KEY="${KEY/#\~/$HOME}"
APP="${JOBBOT_APP_DIR:-/opt/job-alert-bot}"
SERVICE="${JOBBOT_SERVICE:-job-alert-bot}"
RUN_USER="${JOBBOT_USER:-jobbot}"
OPTS=(-o BatchMode=yes)
[ -n "$KEY" ] && OPTS+=(-i "$KEY")
SSH=(ssh "${OPTS[@]}" "$HOST")
SCP=(scp -q "${OPTS[@]}")
PY=python3
[ -x .venv/Scripts/python ] && PY=.venv/Scripts/python
[ -x .venv/bin/python ] && PY=.venv/bin/python

WITH_SECRETS=0; WITH_DB=0; WITH_CV=0
for arg in "$@"; do
  case "$arg" in
    --with-secrets) WITH_SECRETS=1 ;;
    --with-db) WITH_DB=1 ;;
    --with-cv) WITH_CV=1 ;;
    *) echo "unknown option $arg"; exit 1 ;;
  esac
done

for f in config.yml profile.yml companies.yml; do
  [ -f "$f" ] || echo "warning: $f not found locally, the server will use the example file"
done
echo "checking config"
"$PY" -m jobbot check-config >/dev/null || { "$PY" -m jobbot check-config; exit 1; }

# Optional features need extra packages on the server (CV tailoring: anthropic, python-docx).
if [ -z "${JOBBOT_EXTRAS:-}" ]; then
  JOBBOT_EXTRAS="$("$PY" -c '
from jobbot.config import load_config
t = load_config()["tailoring"]
pkgs = []
if t["enabled"] and t["provider"] == "claude":
    pkgs.append("anthropic>=1.0")
if t["enabled"] and (t["docx"] or t["cv_file"].lower().endswith(".docx")):
    pkgs.append("python-docx>=1.1")
print(" ".join(pkgs))')"
fi
if [ "$JOBBOT_EXTRAS" = none ]; then JOBBOT_EXTRAS=""; fi
EXTRAS_QUOTED=""
for pkg in $JOBBOT_EXTRAS; do EXTRAS_QUOTED+=" '$pkg'"; done
if [ -n "$EXTRAS_QUOTED" ]; then echo "extra packages:$EXTRAS_QUOTED"; fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "packing code and config"
tar czf "$TMP/app.tgz" --exclude=.venv --exclude=data --exclude=.env --exclude='.env.*' --exclude=.git \
  --exclude='__pycache__' --exclude='*.pyc' --exclude=.ruff_cache --exclude=deploy/.deploy.env \
  --exclude='cv.*' --exclude=output --exclude=tailored .
"${SCP[@]}" "$TMP/app.tgz" "$HOST:/tmp/jobbot-app.tgz"

if [ "$WITH_SECRETS" = 1 ]; then
  echo "copying .env"
  "${SCP[@]}" .env "$HOST:/tmp/jobbot.env"
fi
if [ "$WITH_DB" = 1 ]; then
  echo "copying database"
  "$PY" -c "import sqlite3; c=sqlite3.connect('data/jobs.db'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()"
  "${SCP[@]}" data/jobs.db "$HOST:/tmp/jobbot-jobs.db"
fi
if [ "$WITH_CV" = 1 ]; then
  CV="$(ls cv.md cv.docx 2>/dev/null | head -1 || true)"
  [ -n "$CV" ] || { echo "no cv.md or cv.docx found"; exit 1; }
  echo "copying $CV"
  "${SCP[@]}" "$CV" "$HOST:/tmp/jobbot-$CV"
fi

echo "installing on server"
"${SSH[@]}" "sudo bash -s" <<EOF
set -euo pipefail
systemctl stop $SERVICE 2>/dev/null || true
mkdir -p $APP/data
tar xzf /tmp/jobbot-app.tgz -C $APP && rm /tmp/jobbot-app.tgz
if [ -f /tmp/jobbot.env ]; then install -m 600 -o $RUN_USER -g $RUN_USER /tmp/jobbot.env $APP/.env && rm /tmp/jobbot.env; fi
if [ -f /tmp/jobbot-jobs.db ]; then install -m 600 -o $RUN_USER -g $RUN_USER /tmp/jobbot-jobs.db $APP/data/jobs.db && rm /tmp/jobbot-jobs.db; fi
for cv in /tmp/jobbot-cv.md /tmp/jobbot-cv.docx; do
  if [ -f "\$cv" ]; then install -m 600 -o $RUN_USER -g $RUN_USER "\$cv" "$APP/\${cv#/tmp/jobbot-}" && rm "\$cv"; fi
done
chown -R $RUN_USER:$RUN_USER $APP
[ -x $APP/.venv/bin/python ] || sudo -u $RUN_USER python3 -m venv $APP/.venv
sudo -u $RUN_USER $APP/.venv/bin/pip install -q --disable-pip-version-check -r $APP/requirements.txt
if [ -n "$EXTRAS_QUOTED" ]; then sudo -u $RUN_USER $APP/.venv/bin/pip install -q --disable-pip-version-check$EXTRAS_QUOTED; fi
sed -e "s#/opt/job-alert-bot#$APP#g" -e "s#^User=jobbot#User=$RUN_USER#" -e "s#^Group=jobbot#Group=$RUN_USER#" \
  $APP/deploy/job-alert-bot.service > /etc/systemd/system/$SERVICE.service
systemctl daemon-reload
systemctl enable --now $SERVICE
sleep 5
systemctl --no-pager --lines=0 status $SERVICE | head -5
EOF
echo "done. Logs: ssh ${KEY:+-i $KEY }$HOST 'journalctl -u $SERVICE -f'"
