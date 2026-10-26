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
git clone https://github.com/spartanxellA/minos-2.git /opt/minos-2
```

Si el repositorio es privado, clónalo con un token de GitHub de solo lectura
(`git clone https://TOKEN@github.com/spartanxellA/minos-2.git /opt/minos-2`) o con una llave de despliegue.

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

## Más workers

Si hay muchos objetivos o fuentes: `minos up -d --scale worker=3`. Con 4 GB caben dos o tres.

## Respaldos

`deploy/backup.sh` guarda la base en `backups/` y conserva 14 días. Para que corra todos los días a las 3:30:

```bash
crontab -e
# agrega la línea:
30 3 * * * /opt/minos-2/deploy/backup.sh >> /var/log/minos-backup.log 2>&1
```

Copia la carpeta `backups/` fuera del servidor de vez en cuando (o activa los respaldos del proveedor del VPS).

Para restaurar uno (reemplaza todo lo que haya en la base):

```bash
cd /opt/minos-2
minos stop api worker
minos exec -T db psql -U minos -d postgres -c "DROP DATABASE minos" -c "CREATE DATABASE minos"
minos exec -T db psql -U minos -d minos -c "CREATE EXTENSION IF NOT EXISTS timescaledb" -c "SELECT timescaledb_pre_restore()"
minos exec -T db pg_restore -U minos -d minos < backups/minos-AAAA-MM-DD.dump
minos exec -T db psql -U minos -d minos -c "SELECT timescaledb_post_restore()"
minos start api worker
```

## Si algo falla

- **No abre el sitio o el certificado falla:** revisa que el dominio apunte a la IP (`ping`) y que los puertos 80 y
  443 estén abiertos en `ufw` y en el firewall del proveedor. `minos logs caddy` dice qué pasó con Let's Encrypt.
- **Olvidaste la contraseña o la cuenta quedó bloqueada:**
  `minos run --rm migrate python -m minos.users password tu@correo.com`
- **Una fuente no trae menciones:** en el tablero, el botón "Fuentes" muestra si cada una tiene llave, cuándo
  consultó y su último error por objetivo. En el servidor, `minos logs --since 10m worker | grep -i error`.
