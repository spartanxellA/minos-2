#!/usr/bin/env bash
# Respaldo diario de minOS: base de datos completa + copia del .env + versión del código.
#
#   deploy/backup.sh                 hace el respaldo (es lo que corre el cron)
#   deploy/backup.sh --install-cron  deja programado el respaldo diario a las 3:30 (hora del servidor)
#   deploy/backup.sh --check         revisa la configuración y que se pueda escribir en la copia externa
#
# Qué hace en cada corrida:
#   1. pg_dump de la base a backups/minos-AAAA-MM-DD.dump y revisa que el archivo se pueda leer.
#   2. Copia el .env a backups/env-AAAA-MM-DD (solo lectura para root) y escribe un manifiesto con el commit del
#      código, la migración de la base, tamaños y sumas sha256.
#   3. Si hay copia externa configurada (BACKUP_S3_* o BACKUP_RCLONE_REMOTE en .env), empaqueta los tres archivos,
#      los cifra con BACKUP_PASSPHRASE y los sube a <destino>/daily/. El día 1 de cada mes también deja una copia en
#      <destino>/monthly/. Borra las diarias de más de BACKUP_REMOTE_KEEP_DAYS y las mensuales de más de
#      BACKUP_REMOTE_KEEP_MONTHS.
#   4. Borra los respaldos locales de más de BACKUP_KEEP_DAYS días.
#   5. Avisa a BACKUP_PING_URL (por ejemplo healthchecks.io): al empezar, al terminar bien o si falla. Si un día no
#      llega el aviso, ese servicio manda un correo.
#
# Para restaurar: deploy/restore.sh (ver "Respaldos" en DEPLOY.md).
# pg_dump avisa de llaves circulares en el catálogo de TimescaleDB: es normal y el respaldo se restaura bien.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=deploy/backup-common.sh
. deploy/backup-common.sh

install_cron() {
  local line="30 3 * * * $PWD/deploy/backup.sh >> /var/log/minos-backup.log 2>&1"
  if crontab -l 2>/dev/null | grep -Fq "deploy/backup.sh"; then
    echo "Ya estaba programado:"
    crontab -l | grep -F "deploy/backup.sh"
  else
    { crontab -l 2>/dev/null || true; echo "$line"; } | crontab -
    echo "Programado: $line"
  fi
}

check() {
  echo "Respaldos locales: $PWD/backups (se guardan $(keep_days) días)"
  if ! remote_configured; then
    echo "Copia externa: NO configurada. Llena BACKUP_S3_* (o BACKUP_RCLONE_REMOTE) y BACKUP_PASSPHRASE en .env."
    return 0
  fi
  require_remote_tools
  local dest probe
  remote_setup
  dest="$DEST"
  probe="$dest/.minos-prueba-$(date +%s)"
  echo "Copia externa: $(remote_label)"
  echo "prueba" | rclone rcat "$probe"
  rclone deletefile "$probe"
  echo "  se pudo escribir y borrar un archivo de prueba: OK"
  echo "  respaldos diarios ahí: $(rclone lsf "$dest/daily" 2>/dev/null | grep -c '' || true)"
  echo "  respaldos mensuales ahí: $(rclone lsf "$dest/monthly" 2>/dev/null | grep -c '' || true)"
  [ -n "$(envget BACKUP_PING_URL)" ] && echo "Aviso: $(envget BACKUP_PING_URL)" || echo "Aviso: sin BACKUP_PING_URL"
}

ping_url() { # ping_url [sufijo] [cuerpo]: no debe tumbar el respaldo si el servicio de avisos no responde
  local url
  url="$(envget BACKUP_PING_URL)"
  [ -n "$url" ] || return 0
  curl -fsS -m 15 --retry 3 -o /dev/null --data-raw "${2:-}" "$url${1:-}" || echo "aviso: no se pudo avisar a $url$1" >&2
}

LOG="$(mktemp)"
on_error() {
  local code=$?
  echo "$(date -Is) ERROR: el respaldo falló (código $code)" | tee -a "$LOG" >&2
  ping_url /fail "$(tail -c 10000 "$LOG")"
  rm -f "$LOG" backups/*.tmp
  exit "$code"
}

backup() {
  trap on_error ERR
  exec > >(tee -a "$LOG") 2>&1
  ping_url /start
  mkdir -p backups
  chmod 700 backups
  local day dump env manifest
  day="$(date +%F)"
  dump="backups/minos-$day.dump"
  env="backups/env-$day"
  manifest="backups/manifest-$day.txt"

  # 1. Base de datos
  compose exec -T db pg_dump -U minos -Fc minos > "$dump.tmp"
  # pg_restore --list lee el índice completo del archivo: si está truncado o dañado, falla aquí y no mañana.
  compose exec -T db pg_restore --list < "$dump.tmp" > /dev/null
  mv "$dump.tmp" "$dump"

  # 2. .env y manifiesto
  if [ -f .env ]; then
    install -m 600 .env "$env"
  else
    echo "aviso: no hay .env que respaldar" >&2
    : > "$env"
  fi
  {
    echo "fecha: $(date -Is)"
    echo "servidor: $(hostname)"
    echo "commit: $(git rev-parse HEAD 2>/dev/null || echo desconocido)"
    echo "migracion: $(compose exec -T db psql -U minos -d minos -tAc 'SELECT version_num FROM alembic_version' 2>/dev/null || echo desconocida)"
    echo "archivos:"
    (cd backups && sha256sum "$(basename "$dump")" "$(basename "$env")" && du -h "$(basename "$dump")")
  } > "$manifest"

  # 3. Copia externa
  if remote_configured; then
    require_remote_tools
    local dest name
    remote_setup
    dest="$DEST"
    name="minos-$day.tar.enc"
    tar -C backups -cf - "$(basename "$dump")" "$(basename "$env")" "$(basename "$manifest")" \
      | encrypt | rclone rcat "$dest/daily/$name"
    # Se baja de nuevo y se descifra para comprobar que la copia externa sirve (con la clave de hoy).
    rclone cat "$dest/daily/$name" | decrypt | tar -tf - | grep -Fx "$(basename "$dump")" > /dev/null
    echo "copia externa lista y comprobada: $(remote_label)/daily/$name ($(rclone size --json "$dest/daily/$name" | sed -n 's/.*"bytes":\([0-9]*\).*/\1/p') bytes)"
    if [ "$(date +%d)" = "01" ]; then
      rclone copyto "$dest/daily/$name" "$dest/monthly/$name"
      echo "copia mensual: $(remote_label)/monthly/$name"
    fi
    rclone delete --min-age "$(remote_keep_days)d" "$dest/daily"
    if rclone lsf "$dest/monthly" > /dev/null 2>&1; then
      rclone delete --min-age "$(( $(remote_keep_months) * 31 ))d" "$dest/monthly"
    fi
  else
    echo "aviso: sin copia externa (los respaldos solo quedan en este servidor). Ver 'Respaldos' en DEPLOY.md." >&2
  fi

  # 4. Retención local
  find backups -maxdepth 1 \( -name 'minos-*.dump' -o -name 'env-*' -o -name 'manifest-*.txt' -o -name 'antes-de-restaurar-*.dump' \) \
    -mtime +"$(keep_days)" -delete

  echo "$(date -Is) respaldo listo: $dump ($(du -h "$dump" | cut -f1)), $(df -h --output=avail . | tail -1 | tr -d ' ') libres en disco"
  ping_url "" "$(tail -c 10000 "$LOG")"
  rm -f "$LOG"
}

case "${1:-}" in
  --install-cron) install_cron ;;
  --check) check ;;
  "") backup ;;
  *) echo "uso: $0 [--install-cron | --check]" >&2; exit 2 ;;
esac
