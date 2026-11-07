# Instalar minOS 2.0 en un servidor

Guía para un VPS con Ubuntu 24.04 y 4 GB de RAM (Hetzner, DigitalOcean, AWS Lightsail u otro). Toma unos 20 minutos.
Al final queda el tablero en `https://tu-dominio` con certificado HTTPS automático, y solo los puertos 80 y 443
abiertos a internet.

```
internet ─▶ Caddy (80/443, HTTPS) ─┬─▶ web (tablero)
                                   └─▶ api (/api, /ws) ─▶ db (TimescaleDB), redis
                                        worker ×N (conectores y motor de riesgo) ─▶ nlp
```

## 1. Contratar el servidor y apuntar el dominio

1. Crea el VPS con **Ubuntu 24.04**, 4 GB de RAM y 2 vCPU, y agrega tu llave SSH al crearlo.
2. Anota la IP pública del servidor.
3. En el panel de DNS de tu dominio crea un registro **A** con el nombre que vayas a usar (por ejemplo `minos`)
   apuntando a esa IP. Si el proveedor da IPv6, agrega también un registro **AAAA**.
4. Espera a que resuelva: `ping minos.tudominio.com` debe responder con la IP del servidor.

## 2. Preparar el servidor

Conéctate con `ssh root@IP` y corre:

```bash
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh          # Docker y docker compose
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443 && ufw --force enable
```

El repositorio es privado en GitLab. Crea una llave de despliegue de solo lectura en el servidor:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/minos_gitlab -N "" -C "minos-servidor" && cat ~/.ssh/minos_gitlab.pub
```

Agrega esa línea en GitLab, en Settings → Repository → Deploy keys, sin marcar "Grant write permissions". Luego clona:

```bash
git clone -c core.sshCommand="ssh -i ~/.ssh/minos_gitlab -o IdentitiesOnly=yes" git@gitlab.com:aen-group1/minos-2.git /opt/minos-2
```

La primera vez SSH pregunta por la huella de `gitlab.com`; debe ser `SHA256:eUXGGm1YGsMAS7vkcx6JOJdOGHPem5gQp4taiCfCLB8`.

Con 2 GB de RAM agrega 2 GB de memoria de intercambio (swap) para que la construcción no se quede sin memoria:

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

## 3. Configurar

```bash
cd /opt/minos-2
cp .env.example .env
nano .env
```

Llena como mínimo (el modo producción, el inicio de sesión y apagar los datos de demostración ya los fija
`docker-compose.prod.yml`):

| Variable | Valor |
| --- | --- |
| `DOMAIN` | `minos.tudominio.com` (sin `https://`) |
| `ACME_EMAIL` | tu correo, para avisos del certificado |
| `POSTGRES_PASSWORD` | el resultado de `openssl rand -hex 24` |
| `ADMIN_EMAIL` | el correo del primer administrador |
| `ADMIN_PASSWORD` | una contraseña de al menos 10 caracteres |

Después agrega las llaves de las fuentes que tengas (X, YouTube, Bluesky, Reddit, Meta) y de los avisos (correo,
webhook, WhatsApp). Las que queden vacías quedan apagadas.

## 4. Arrancar

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

La primera vez tarda unos minutos en construir. Al terminar abre `https://minos.tudominio.com` y entra con
`ADMIN_EMAIL` y `ADMIN_PASSWORD`. Ya dentro, cambia la contraseña desde "Contraseña", crea las cuentas del equipo en
"Usuarios" y borra `ADMIN_PASSWORD` del `.env` (solo se usa cuando no hay ninguna cuenta).

Para no escribir los dos archivos cada vez:

```bash
echo 'alias minos="docker compose -f /opt/minos-2/docker-compose.yml -f /opt/minos-2/docker-compose.prod.yml"' >> ~/.bashrc
source ~/.bashrc
minos ps            # estado de los servicios
minos logs -f api   # registros de la API (o worker, caddy, db...)
```

## Actualizar

```bash
cd /opt/minos-2 && git pull
minos up -d --build      # el servicio migrate aplica las migraciones nuevas antes de arrancar la API
```

Antes de una actualización grande puedes sacar un respaldo a mano con `deploy/backup.sh`.

## Más workers

Si hay muchos objetivos o fuentes: `minos up -d --scale worker=3`. Con 4 GB caben dos o tres.

## Respaldos

Hay tres capas; con las tres siempre hay de dónde restaurar:

| Capa | Qué guarda | Dónde | Cuánto tiempo |
| --- | --- | --- | --- |
| Código | todo el programa y las migraciones | GitHub (cada PR fusionado) | siempre |
| `deploy/backup.sh` | base completa + `.env` + versión del código | `/opt/minos-2/backups/` y copia externa cifrada | 14 días aquí; 30 diarios y 12 mensuales fuera |
| Backups de DigitalOcean | el Droplet entero (disco completo) | DigitalOcean | según el plan del panel |

Los Backups de DigitalOcean se activan en el panel: *Droplet → Backups → Enable* (semanales, o diarios con costo
extra). No necesitan nada en el servidor.

### Configurar (una sola vez)

1. **Crear dónde guardar la copia externa.** En DigitalOcean: *Spaces Object Storage → Create Space*, en una región
   distinta a la del Droplet si se puede, acceso **privado** (sin CDN). Luego *Spaces Keys → Generate New Key*, con
   acceso solo a ese Space (lectura, escritura y borrado). Anota el nombre del Space, el endpoint, la llave y el
   secreto (DigitalOcean muestra el secreto una sola vez). Funciona igual con Backblaze B2 o AWS S3 (ver
   `.env.example`).
   - **Endpoint:** solo la región, **sin** el nombre del Space. Si la dirección del Space es
     `https://minos.sfo3.digitaloceanspaces.com`, el endpoint es `sfo3.digitaloceanspaces.com` y el bucket es `minos`.
   - **Llave:** es una *Spaces Access Key* (suele empezar con `DO`, unos 20 caracteres; el secreto tiene unos 43). Un
     token de la API de DigitalOcean (`dop_v1_...`) no sirve aquí.
2. **Instalar rclone** (sube los archivos): `apt install -y rclone`.
3. **Llenar en `.env`:** `BACKUP_S3_ENDPOINT`, `BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY`, `BACKUP_S3_SECRET_KEY` y
   `BACKUP_PASSPHRASE` (genera una con `openssl rand -base64 32`).
4. **Guardar fuera del servidor**, en un gestor de contraseñas: `BACKUP_PASSPHRASE`, y la llave y el secreto del
   Space. Si el servidor se pierde, esas tres cosas bastan para recuperarlo todo; sin la frase, la copia externa no
   se puede abrir.
5. **Aviso si falla (recomendado):** crea una cuenta gratis en [healthchecks.io](https://healthchecks.io), un check
   con periodo de 1 día y gracia de 2 horas, y pon su URL en `BACKUP_PING_URL`. Si un día el respaldo falla o no
   corre, te llega un correo.
6. **Probar y programar:**

```bash
cd /opt/minos-2
deploy/backup.sh --check          # revisa la configuración y que se pueda escribir en el Space
deploy/backup.sh                  # primer respaldo ahora
deploy/backup.sh --install-cron   # todos los días a las 3:30 (hora del servidor, UTC = 21:30 en CDMX)
```

### Qué hace cada noche

1. `pg_dump` de la base a `backups/minos-AAAA-MM-DD.dump` y comprueba que el archivo se pueda leer.
2. Copia el `.env` a `backups/env-AAAA-MM-DD` y escribe `backups/manifest-AAAA-MM-DD.txt` con el commit del código,
   la migración de la base y las sumas sha256.
3. Empaqueta los tres, los cifra (AES-256) y los sube a `<Space>/minos/daily/`. Después lo baja y lo descifra para
   confirmar que la copia sirve. El día 1 de cada mes deja además una copia en `monthly/`.
4. Borra lo viejo: aquí más de `BACKUP_KEEP_DAYS` días; fuera, diarios de más de `BACKUP_REMOTE_KEEP_DAYS` días y
   mensuales de más de `BACKUP_REMOTE_KEEP_MONTHS` meses.
5. Avisa a `BACKUP_PING_URL` si terminó bien o falló.

Para revisar: `tail /var/log/minos-backup.log` o `deploy/restore.sh list`.

### Restaurar la base

```bash
cd /opt/minos-2
deploy/restore.sh list            # fechas disponibles, aquí y en la copia externa
deploy/restore.sh 2026-11-02      # pide escribir RESTAURAR
```

Usa el archivo local si está y si no lo baja de la copia externa. Antes de reemplazar nada guarda la base actual en
`backups/antes-de-restaurar-<fecha y hora>.dump` (se puede volver a ella con los mismos pasos), hace los pasos que
pide TimescaleDB, y al arrancar de nuevo `migrate` aplica las migraciones que el respaldo no tenga.

### Si se pierde el servidor completo

- **Lo más rápido:** en el panel de DigitalOcean, *Droplet → Backups → Restore Droplet* (o crear un Droplet nuevo
  desde ese backup). Vuelve todo como estaba el día del backup. Si el backup del Droplet es más viejo que el último
  respaldo nocturno, después restaura la base con `deploy/restore.sh` para recuperar los días que falten.
- **Sin backup del Droplet (o en otro proveedor):** con la frase y las llaves del Space guardadas en el gestor de
  contraseñas.

```bash
# 1. Servidor nuevo con Docker y el código (pasos 1 y 2 de esta guía), y rclone
apt install -y rclone
cd /opt/minos-2
# 2. Bajar el último respaldo con las llaves del gestor de contraseñas (no hace falta .env todavía)
BACKUP_S3_ENDPOINT=nyc3.digitaloceanspaces.com BACKUP_S3_BUCKET=nombre-del-space \
BACKUP_S3_ACCESS_KEY=... BACKUP_S3_SECRET_KEY=... BACKUP_PASSPHRASE='...' deploy/restore.sh list
#    (mismas variables) deploy/restore.sh fetch AAAA-MM-DD
# 3. Recuperar el .env de ese día y restaurar la base
cp backups/env-AAAA-MM-DD .env && chmod 600 .env
minos up -d --build
deploy/restore.sh AAAA-MM-DD
deploy/backup.sh --install-cron
```

Si la IP cambió, actualiza el registro A del dominio. Para abrir un respaldo a mano en cualquier computadora:
`openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in minos-AAAA-MM-DD.tar.enc | tar -xf -` (pide la frase).

### Ensayo

Una vez al mes conviene comprobar que todo sirve: `deploy/restore.sh list` debe mostrar respaldos de los últimos
días, y `deploy/restore.sh fetch <ayer>` debe terminar sin errores (solo baja y revisa, no cambia nada). El CI
también respalda y restaura una base real de TimescaleDB en cada cambio.

## Si algo falla

- **No abre el sitio o el certificado falla:** revisa que el dominio apunte a la IP (`ping`) y que los puertos 80 y
  443 estén abiertos en `ufw` y en el firewall del proveedor. `minos logs caddy` dice qué pasó con Let's Encrypt.
- **Olvidaste la contraseña o la cuenta quedó bloqueada:**
  `minos run --rm migrate python -m minos.users password tu@correo.com` (también quita los bloqueos por intentos).
  Un bloqueo por intentos desde otra IP no te impide entrar desde la tuya; los bloqueos vencen solos en 15 minutos.
  Caddy no acepta `X-Forwarded-For` de fuera, así que la IP que cuenta es la real de quien se conecta.
- **`deploy/backup.sh --check` falla:**
  - `x509: certificate is valid for *.internal.digitalocean.com`: el endpoint lleva el nombre del Space al principio
    (la dirección sale duplicada, `minos.minos.sfo3...`). Deja solo `BACKUP_S3_ENDPOINT=sfo3.digitaloceanspaces.com`.
  - `InvalidAccessKeyId`: la llave no es una Spaces Access Key válida (token de la API, llave y secreto al revés, o un
    espacio de más). Crea otra en *Spaces Object Storage → Access Keys*.
  - `SignatureDoesNotMatch`: la llave existe pero el secreto no corresponde.
  - `AccessDenied`: la llave no tiene permiso sobre ese Space, o el nombre del bucket está mal.
  - `Falta BACKUP_PASSPHRASE`: la copia externa siempre va cifrada; agrega la frase al `.env`.
- **Ver cómo van los respaldos:** `tail /var/log/minos-backup.log`, `deploy/restore.sh list` y `crontab -l` (debe
  aparecer `backup.sh`).
- **Una fuente no trae menciones:** en el tablero, el botón "Fuentes" muestra si cada una tiene llave, cuándo
  consultó y su último error por objetivo. En el servidor, `minos logs --since 10m worker | grep -i error`.
- **Errores de fuentes en el log del worker** (también salen en "Fuentes"). El worker pausa solo la fuente o el feed
  y no lo vuelve a pedir en cada ronda; el aviso dice hasta qué hora:
  - `429 Too Many Requests` en un feed RSS: el sitio pide esperar. Se respeta `Retry-After` (o 15 min que se duplican
    hasta 6 h) y los feeds de `RSS_FEEDS` se descargan una vez por ronda para todos los objetivos. No requiere nada.
  - `402 Payment Required` en un feed (por ejemplo `rss.app`): el plan del servicio venció. Renuévalo o quita ese
    feed de `RSS_FEEDS`.
  - `403 Forbidden` en un feed: el sitio bloquea lectores automáticos. minOS ya se presenta como navegador; si sigue,
    el sitio tiene protección anti-bots (Cloudflare) y conviene quitar el feed o buscar su liga en Google Noticias.
  - `402` en X: el plan de la API de X no tiene créditos. X queda en pausa 6 h (luego 12 y 24) para todos los
    objetivos; recarga o cambia el plan en developer.x.com.
  - `403 quotaExceeded` o `429` en YouTube: se acabó la cuota diaria (10,000 unidades; cada búsqueda gasta ~101).
    YouTube queda en pausa hasta que Google la reinicia (medianoche del Pacífico). minOS ya alarga el intervalo según
    el número de objetivos; si pides más cuota en Google Cloud, súbela en `YOUTUBE_DAILY_QUOTA`.
