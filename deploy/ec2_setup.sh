#!/usr/bin/env bash
# One-shot, idempotent setup for Part I (IaaS) on Ubuntu 24.04 EC2.
# Installs MySQL + nginx + Python, loads the database, and runs the app with gunicorn under systemd.
#
# Usage (as the ubuntu user):
#   curl -fsSL https://raw.githubusercontent.com/ZaryanNabeel/f1fantasy/main/deploy/ec2_setup.sh -o ec2_setup.sh
#   bash ec2_setup.sh            # clones https://github.com/ZaryanNabeel/f1fantasy.git; override with REPO_URL=...
#
# You will be asked for two passwords (use letters and digits only, 12+ chars):
#   - f1app  : the account the app uses (read/write)
#   - grader : the read-only account for the evaluation script
# Safe to re-run: existing database rows, users, and the SECRET_KEY are kept.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/ZaryanNabeel/f1fantasy.git}"
APP_DIR=/home/ubuntu/f1fantasy
ENV_FILE=/etc/f1fantasy.env
MYSQL_CNF=/etc/mysql/mysql.conf.d/mysqld.cnf

read_pw() {  # read_pw VAR "prompt": keep env value if already set
  local var="$1"
  if [ -z "${!var:-}" ]; then read -rsp "$2: " "$var"; echo; fi
  [[ "${!var}" =~ ^[A-Za-z0-9]{12,}$ ]] || { echo "$var must be 12+ letters/digits"; exit 1; }
}
read_pw APP_DB_PASSWORD "Password for MySQL user f1app"
read_pw GRADER_DB_PASSWORD "Password for MySQL user grader"

echo "==> 1/7 Installing packages"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-pip nginx mysql-server git

echo "==> 2/7 MySQL: listen on all interfaces so the grader can connect remotely"
sudo sed -i 's/^\s*bind-address\s*=.*/bind-address = 0.0.0.0/' "$MYSQL_CNF"
grep -q '^bind-address' "$MYSQL_CNF" || echo 'bind-address = 0.0.0.0' | sudo tee -a "$MYSQL_CNF" >/dev/null
sudo systemctl enable --now mysql
sudo systemctl restart mysql

echo "==> 3/7 Getting the code"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone "$REPO_URL" "$APP_DIR"
fi
sudo chown -R ubuntu:ubuntu "$APP_DIR"

echo "==> 4/7 Loading schema, seed and accounts (root uses socket auth: sudo mysql)"
sudo mysql < "$APP_DIR/sql/schema.sql"
if [ "$(sudo mysql -N -e 'SELECT COUNT(*) FROM f1fantasy.teams')" = "0" ]; then
  sudo mysql < "$APP_DIR/sql/seed_2026.sql"
else
  echo "    seed already loaded, skipping"
fi
sed -e "s/CHANGE_ME_APP/${APP_DB_PASSWORD}/" -e "s/CHANGE_ME_GRADER/${GRADER_DB_PASSWORD}/" \
  "$APP_DIR/sql/create_users.sql" | sudo mysql

echo "==> 5/7 Python virtualenv"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> 6/7 Environment file $ENV_FILE (mode 600, owner ubuntu)"
if sudo test -f "$ENV_FILE"; then
  SECRET_KEY=$(sudo grep '^SECRET_KEY=' "$ENV_FILE" | cut -d= -f2-)
fi
SECRET_KEY="${SECRET_KEY:-$(python3 -c 'import secrets; print(secrets.token_hex(32))')}"
sudo tee "$ENV_FILE" >/dev/null <<EOF
FLASK_ENV=production
SECRET_KEY=${SECRET_KEY}
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=f1fantasy
DB_USER=f1app
DB_PASSWORD=${APP_DB_PASSWORD}
F1_SEASON=2026
EOF
sudo chown ubuntu:ubuntu "$ENV_FILE"
sudo chmod 600 "$ENV_FILE"

echo "==> 7/7 systemd service + nginx site"
sudo cp "$APP_DIR/deploy/f1fantasy.service" /etc/systemd/system/f1fantasy.service
sudo systemctl daemon-reload
sudo systemctl enable f1fantasy
sudo systemctl restart f1fantasy
sudo cp "$APP_DIR/deploy/nginx_f1fantasy.conf" /etc/nginx/sites-available/f1fantasy
sudo ln -sf /etc/nginx/sites-available/f1fantasy /etc/nginx/sites-enabled/f1fantasy
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

sleep 2
echo "==> Health check:"
curl -fsS http://127.0.0.1/health && echo
echo "Done. Next: create the admin and demo users (see DEPLOYMENT.md step I-6)."
