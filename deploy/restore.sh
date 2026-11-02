#!/usr/bin/env bash
# Restaurar minOS desde un respaldo de deploy/backup.sh.
#
#   deploy/restore.sh list                 respaldos disponibles (en este servidor y en la copia externa)
#   deploy/restore.sh fetch AAAA-MM-DD     baja de la copia externa y descifra a backups/ (base, .env y manifiesto)
#                                          sin tocar nada: sirve para recuperar el .env en un servidor nuevo
#   deploy/restore.sh AAAA-MM-DD [--yes]   reemplaza la base actual por la de ese día
#
# Antes de reemplazar la base guarda la actual en backups/antes-de-restaurar-<fecha y hora>.dump, por si acaso.
# El .env nunca se sobrescribe solo: queda en backups/env-AAAA-MM-DD para copiarlo a mano si hace falta.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=deploy/backup-common.sh
. deploy/backup-common.sh

valid_day() { [[ "$1" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "Fecha inválida: $1 (usa AAAA-MM-DD)" >&2; exit 2; }; }

list() {
  echo "En este servidor ($PWD/backups):"
  ls -1 backups/minos-*.dump 2>/dev/null | sed 's|backups/minos-||; s|\.dump$||; s|^|  |' || true
  ls -1 backups/antes-de-restaurar-*.dump 2>/dev/null | sed 's|^|  |' || true
  if remote_configured; then
    require_remote_tools
    remote_setup
    echo "En la copia externa $(remote_label):"
    echo "  diarios:";   rclone lsf "$DEST/daily" 2>/dev/null | sed 's|^minos-||; s|\.tar\.enc$||; s|^|    |' || true
    echo "  mensuales:"; rclone lsf "$DEST/monthly" 2>/dev/null | sed 's|^minos-||; s|\.tar\.enc$||; s|^|    |' || true
  else
    echo "(sin copia externa configurada)"
  fi
}

fetch() { # baja y descifra el respaldo del día $1 a backups/
  local day="$1" name src
  valid_day "$day"
  remote_configured || { echo "No hay copia externa configurada (BACKUP_S3_* o BACKUP_RCLONE_REMOTE)." >&2; exit 1; }
  require_remote_tools
  remote_setup
  name="minos-$day.tar.enc"
  if rclone lsf "$DEST/daily/$name" 2>/dev/null | grep -Fx "$name" > /dev/null; then
    src="$DEST/daily/$name"
  elif rclone lsf "$DEST/monthly/$name" 2>/dev/null | grep -Fx "$name" > /dev/null; then
    src="$DEST/monthly/$name"
  else
    echo "No existe $name en la copia externa. Ver: deploy/restore.sh list" >&2
    exit 1
  fi
  mkdir -p backups
  chmod 700 backups
  echo "Bajando $src ..."
  if ! rclone cat "$src" | decrypt | tar -C backups -xf -; then
    echo "No se pudo bajar o descifrar $name. ¿BACKUP_PASSPHRASE es la misma que cuando se hizo el respaldo?" >&2
    exit 1
  fi
  chmod 600 "backups/env-$day" 2>/dev/null || true
  # Las sumas del manifiesto confirman que la base y el .env llegaron completos.
  (cd backups && grep -E '^[0-9a-f]{64}  ' "manifest-$day.txt" | sha256sum -c --quiet) \
    || { echo "Las sumas sha256 no coinciden con el manifiesto: el respaldo está dañado." >&2; exit 1; }
  echo "Listo en backups/: minos-$day.dump, env-$day (el .env de ese día) y manifest-$day.txt"
}

wait_db() {
  compose up -d db > /dev/null
  for _ in $(seq 60); do
    compose exec -T db pg_isready -U minos -d postgres > /dev/null 2>&1 && return 0
    sleep 2
  done
  echo "La base no arrancó. Revisa: docker compose logs db" >&2
  exit 1
}

restore() {
  local day="$1" yes="${2:-}" dump
  valid_day "$day"
  dump="backups/minos-$day.dump"
  if [ ! -f "$dump" ]; then
    echo "No está $dump en este servidor; se busca en la copia externa."
    fetch "$day"
  fi
  [ -f "backups/manifest-$day.txt" ] && { echo "--- manifiesto del respaldo ---"; cat "backups/manifest-$day.txt"; echo "---"; }
  if [ "$yes" != "--yes" ]; then
    echo "Esto REEMPLAZA toda la base actual de minOS por la del $day."
    read -r -p "Escribe RESTAURAR para continuar: " answer
    [ "$answer" = "RESTAURAR" ] || { echo "Cancelado, no se cambió nada."; exit 1; }
  fi

  wait_db
  local safety
  safety="backups/antes-de-restaurar-$(date +%F-%H%M%S).dump"
  if compose exec -T db pg_dump -U minos -Fc minos > "$safety" 2>/dev/null; then
    echo "Base actual guardada en $safety"
  else
    rm -f "$safety"
    echo "aviso: no se pudo guardar la base actual (¿servidor nuevo sin base?); se sigue." >&2
  fi

  compose stop api worker 2>/dev/null || true
  compose exec -T db psql -v ON_ERROR_STOP=1 -U minos -d postgres -c "DROP DATABASE IF EXISTS minos WITH (FORCE)" -c "CREATE DATABASE minos"
  # TimescaleDB necesita estos pasos alrededor de pg_restore para que la tabla de historial de riesgo quede bien.
  compose exec -T db psql -v ON_ERROR_STOP=1 -U minos -d minos -c "CREATE EXTENSION IF NOT EXISTS timescaledb" -c "SELECT timescaledb_pre_restore()"
  local rc=0
  compose exec -T db pg_restore -U minos -d minos < "$dump" || rc=$?
  compose exec -T db psql -v ON_ERROR_STOP=1 -U minos -d minos -c "SELECT timescaledb_post_restore()"
  [ "$rc" = 0 ] || echo "aviso: pg_restore terminó con avisos (código $rc); revisa los mensajes de arriba." >&2

  echo "Objetivos en la base restaurada: $(compose exec -T db psql -U minos -d minos -tAc 'SELECT count(*) FROM targets' || echo '?')"
  echo "Menciones: $(compose exec -T db psql -U minos -d minos -tAc 'SELECT count(*) FROM mentions' || echo '?')"
  # "up" vuelve a correr migrate (aplica migraciones más nuevas que el respaldo, si las hay) y arranca api y worker.
  compose up -d
  echo "Restauración terminada."
}

case "${1:-}" in
  list) list ;;
  fetch) [ -n "${2:-}" ] || { echo "uso: $0 fetch AAAA-MM-DD" >&2; exit 2; }; fetch "$2" ;;
  "" | -h | --help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) restore "$1" "${2:-}" ;;
esac
