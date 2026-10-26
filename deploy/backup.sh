#!/usr/bin/env sh
# Respaldo diario de la base. Programarlo en el servidor con: crontab -e
#   30 3 * * * /opt/minos-2/deploy/backup.sh >> /var/log/minos-backup.log 2>&1
# Para restaurar uno, ver "Respaldos" en DEPLOY.md (TimescaleDB necesita pasos antes y después de pg_restore).
# pg_dump avisa de llaves circulares en el catálogo de TimescaleDB: es normal y el respaldo se restaura bien.
set -eu
cd "$(dirname "$0")/.."
mkdir -p backups
file="backups/minos-$(date +%F).dump"
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db pg_dump -U minos -Fc minos > "$file.tmp"
mv "$file.tmp" "$file"
# Se guardan los últimos 14 días.
find backups -name 'minos-*.dump' -mtime +14 -delete
echo "$(date -Is) respaldo listo: $file ($(du -h "$file" | cut -f1))"
