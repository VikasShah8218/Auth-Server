#!/bin/sh
# Dump the database to deploy/backups/, keeping the newest $KEEP (default 14).
#   ./backup.sh              # e.g. from cron: 0 3 * * * /opt/Auth-Server/deploy/backup.sh
# Restore:
#   gunzip -c backups/auth-YYYYMMDD-HHMMSS.sql.gz | docker compose exec -T postgres psql -U auth -d auth
# The dump does NOT contain MASTER_KEY. Keep a copy of .env somewhere safe as well.
set -eu
cd "$(dirname "$0")"
mkdir -p backups
file="backups/auth-$(date +%Y%m%d-%H%M%S).sql.gz"
docker compose exec -T postgres pg_dump -U auth -d auth --clean --if-exists | gzip > "$file"
ls -1t backups/auth-*.sql.gz | tail -n +"$(( ${KEEP:-14} + 1 ))" | xargs -r rm --
echo "Backup written: $file"
