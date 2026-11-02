# Funciones compartidas por deploy/backup.sh y deploy/restore.sh. No se ejecuta sola.
# La configuración sale de variables de entorno o, si no están, del .env (se lee línea por línea, sin ejecutarlo).

envget() { # envget NOMBRE: valor de NOMBRE en el entorno o en .env, sin comillas alrededor
  local name="$1" value
  value="${!name:-}"
  if [ -z "$value" ] && [ -f .env ]; then
    value="$(grep -E "^[[:space:]]*$name=" .env | tail -1 | cut -d= -f2- | tr -d '\r')" || true
    value="${value#\"}"; value="${value%\"}"; value="${value#\'}"; value="${value%\'}"
  fi
  printf '%s' "$value"
}

# Sin archivo de configuración de rclone (lo normal con BACKUP_S3_*), que no avise en cada comando.
[ -n "${RCLONE_CONFIG:-}" ] || [ -f "$HOME/.config/rclone/rclone.conf" ] || export RCLONE_CONFIG=/dev/null

compose() {
  # MINOS_COMPOSE permite cambiar el comando (por ejemplo, en pruebas). En el servidor no hace falta.
  if [ -n "${MINOS_COMPOSE:-}" ]; then
    # shellcheck disable=SC2086
    $MINOS_COMPOSE "$@"
  else
    docker compose -f docker-compose.yml -f docker-compose.prod.yml "$@"
  fi
}

keep_days() { local v; v="$(envget BACKUP_KEEP_DAYS)"; echo "${v:-14}"; }
remote_keep_days() { local v; v="$(envget BACKUP_REMOTE_KEEP_DAYS)"; echo "${v:-30}"; }
remote_keep_months() { local v; v="$(envget BACKUP_REMOTE_KEEP_MONTHS)"; echo "${v:-12}"; }

remote_configured() { [ -n "$(envget BACKUP_RCLONE_REMOTE)" ] || [ -n "$(envget BACKUP_S3_BUCKET)" ]; }

remote_setup() { # deja en DEST el destino para rclone (no usar dentro de $(...): exporta variables)
  local custom
  custom="$(envget BACKUP_RCLONE_REMOTE)"
  if [ -n "$custom" ]; then
    DEST="${custom%/}"
    return
  fi
  # Remoto S3 definido al vuelo (DigitalOcean Spaces, Backblaze B2, AWS S3, Wasabi...): no hace falta "rclone config".
  export RCLONE_CONFIG_MINOSS3_TYPE=s3
  RCLONE_CONFIG_MINOSS3_PROVIDER="$(envget BACKUP_S3_PROVIDER)"
  export RCLONE_CONFIG_MINOSS3_PROVIDER="${RCLONE_CONFIG_MINOSS3_PROVIDER:-DigitalOcean}"
  RCLONE_CONFIG_MINOSS3_ENDPOINT="$(endpoint)"
  RCLONE_CONFIG_MINOSS3_REGION="$(envget BACKUP_S3_REGION)"
  RCLONE_CONFIG_MINOSS3_ACCESS_KEY_ID="$(envget BACKUP_S3_ACCESS_KEY)"
  RCLONE_CONFIG_MINOSS3_SECRET_ACCESS_KEY="$(envget BACKUP_S3_SECRET_KEY)"
  export RCLONE_CONFIG_MINOSS3_ENDPOINT RCLONE_CONFIG_MINOSS3_REGION RCLONE_CONFIG_MINOSS3_ACCESS_KEY_ID \
    RCLONE_CONFIG_MINOSS3_SECRET_ACCESS_KEY
  export RCLONE_CONFIG_MINOSS3_ACL=private RCLONE_CONFIG_MINOSS3_NO_CHECK_BUCKET=true
  local prefix
  prefix="$(envget BACKUP_S3_PREFIX)"
  DEST="minoss3:$(envget BACKUP_S3_BUCKET)/${prefix:-minos}"
}

endpoint() { # BACKUP_S3_ENDPOINT sin https:// ni el nombre del bucket delante (error común al copiarlo del panel)
  local e bucket
  e="$(envget BACKUP_S3_ENDPOINT)"; bucket="$(envget BACKUP_S3_BUCKET)"
  e="${e#https://}"; e="${e#http://}"; e="${e%/}"
  [ -n "$bucket" ] && e="${e#"$bucket".}"
  printf '%s' "$e"
}

remote_label() { # destino para mostrar en registros, sin llaves
  local custom prefix
  custom="$(envget BACKUP_RCLONE_REMOTE)"
  if [ -n "$custom" ]; then printf '%s' "${custom%/}"; return; fi
  prefix="$(envget BACKUP_S3_PREFIX)"
  printf 's3://%s/%s (%s)' "$(envget BACKUP_S3_BUCKET)" "${prefix:-minos}" "$(endpoint)"
}

require_remote_tools() {
  command -v rclone > /dev/null || { echo "Falta rclone. Instálalo con: apt install -y rclone" >&2; return 1; }
  command -v openssl > /dev/null || { echo "Falta openssl. Instálalo con: apt install -y openssl" >&2; return 1; }
  [ -n "$(envget BACKUP_PASSPHRASE)" ] || {
    echo "Falta BACKUP_PASSPHRASE en .env: la copia externa siempre va cifrada (lleva la base y las llaves)." >&2
    return 1
  }
}

# AES-256 con clave derivada de BACKUP_PASSPHRASE (PBKDF2). Para descifrar a mano en cualquier máquina:
#   openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in minos-AAAA-MM-DD.tar.enc | tar -xf -
encrypt() { MINOS_BACKUP_PASS="$(envget BACKUP_PASSPHRASE)" openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:MINOS_BACKUP_PASS; }
decrypt() { MINOS_BACKUP_PASS="$(envget BACKUP_PASSPHRASE)" openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:MINOS_BACKUP_PASS; }
