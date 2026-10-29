#!/bin/bash
# Runs once, the first time the MySQL data volume is empty.
set -e
mysql_root() { mysql --protocol=socket -uroot -p"$MYSQL_ROOT_PASSWORD" "$@"; }

echo ">> Creating database $APP_DB_NAME"
mysql_root -e "CREATE DATABASE IF NOT EXISTS \`$APP_DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

echo ">> Loading schema"
mysql_root --default-character-set=utf8mb4 "$APP_DB_NAME" < /sql/schema.sql

if [ -f /sql/seed_2026.sql ]; then
  echo ">> Loading 2026 seed data"
  mysql_root --default-character-set=utf8mb4 "$APP_DB_NAME" < /sql/seed_2026.sql
fi

echo ">> Creating app and read-only grader accounts"
mysql_root <<SQL
CREATE USER IF NOT EXISTS '$APP_DB_USER'@'%' IDENTIFIED BY '$APP_DB_PASSWORD';
GRANT ALL PRIVILEGES ON \`$APP_DB_NAME\`.* TO '$APP_DB_USER'@'%';
CREATE USER IF NOT EXISTS 'grader'@'%' IDENTIFIED BY '$GRADER_PASSWORD';
GRANT SELECT ON \`$APP_DB_NAME\`.* TO 'grader'@'%';
FLUSH PRIVILEGES;
SQL
echo ">> Database init complete"
