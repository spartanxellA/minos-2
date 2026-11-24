# Configuración de minOS 2.0

La API y los workers leen variables `MINOS_*` (`backend/minos/config.py`). Las secciones se separan con `__`, las
duraciones van en segundos (o ISO 8601, `PT5M`) y las listas y diccionarios en JSON.

Con Docker se llena `.env` (plantilla: `.env.example`) y `docker-compose.yml` traduce cada nombre corto a su variable
`MINOS_*`. La columna "En Docker" dice el nombre corto; "fijo en Compose" es un valor que pone Compose, y "—" significa
que la variable **no llega** a los contenedores. `docker-compose.prod.yml` fija además `MINOS_ENV=production`, el inicio
de sesión, los datos de demostración apagados y las direcciones a partir de `DOMAIN`.

## Variables que no llegan a Docker

Escribir en `.env` una variable con "—" no tiene efecto en el servidor, porque los contenedores solo reciben las que
nombra `docker-compose.yml`. Para usarla, crea un archivo de Compose aparte, que `git pull` no toca:

```yaml
# /opt/minos-2/docker-compose.local.yml
services:
  api:
    environment: &propias
      MINOS_AUTH__MAX_FAILED_LOGINS: "8"
      MINOS_TIMEZONE: America/Monterrey
  worker:
    environment: *propias
```

y agrégalo al final del comando (o del alias `minos`): `-f docker-compose.local.yml`. Los scripts de `deploy/` usan solo
los dos archivos base, que bastan para respaldar y restaurar.

## Referencia

### General

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_ENV` | development | `MINOS_ENV` |
| `MINOS_DATABASE_URL` | base local `minos` | `POSTGRES_PASSWORD` |
| `MINOS_NLP_URL` | (vacío) | fijo en Compose |
| `MINOS_CORS_ORIGINS` | `["http://localhost:3000"]` | fijo en Compose |
| `MINOS_SURVEYS_PATH` | data/surveys.json | — |
| `MINOS_ROLE` | all | fijo en Compose |
| `MINOS_REDIS_URL` | (vacío) | fijo en Compose |
| `MINOS_CREATE_SCHEMA` | false | — |
| `MINOS_TIMEZONE` | America/Mexico_City | — |

### Cuentas y sesión

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_AUTH__MODE` | local | `AUTH_MODE` |
| `MINOS_AUTH__SESSION_TTL` | 604800 s | — |
| `MINOS_AUTH__IDLE_TIMEOUT` | 1800 s | `IDLE_TIMEOUT_SECONDS` |
| `MINOS_AUTH__COOKIE_NAME` | minos_session | — |
| `MINOS_AUTH__MAX_FAILED_LOGINS` | 5 | — |
| `MINOS_AUTH__LOCKOUT` | 900 s | — |
| `MINOS_AUTH__ACCOUNT_MAX_FAILED_LOGINS` | 30 | — |
| `MINOS_AUTH__ACCOUNT_WINDOW` | 3600 s | — |
| `MINOS_AUTH__IP_MAX_FAILED_LOGINS` | 20 | — |
| `MINOS_AUTH__IP_WINDOW` | 900 s | — |
| `MINOS_AUTH__SECURITY_ALERTS_PER_HOUR` | 6 | — |
| `MINOS_AUTH__MIN_PASSWORD_LENGTH` | 10 | — |
| `MINOS_AUTH__BOOTSTRAP_ADMIN_EMAIL` | (vacío) | `ADMIN_EMAIL` |
| `MINOS_AUTH__BOOTSTRAP_ADMIN_PASSWORD` | (vacío) | `ADMIN_PASSWORD` |

### Datos de demostración

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_DEMO__ENABLED` | false | `DEMO_ENABLED` |
| `MINOS_DEMO__POLL_INTERVAL` | 20 s | — |

### Ingesta

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_INGESTION__TICK` | 30 s | — |
| `MINOS_INGESTION__MAX_MENTIONS_PER_RUN` | 300 | — |
| `MINOS_INGESTION__DUPLICATE_WINDOW` | 259200 s | — |
| `MINOS_INGESTION__LOCK_TTL` | 600 s | — |

### Mapa

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_INGESTION__GEO__ENABLED` | true | — |
| `MINOS_INGESTION__GEO__DEFAULT_COUNTRY` | MX | — |
| `MINOS_INGESTION__GEO__FROM_TEXT` | true | — |

### Motor de riesgo

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_RISK_ENGINE__FULL_RECOMPUTE_EVERY` | 60 s | — |
| `MINOS_RISK_ENGINE__WINDOW` | 86400 s | — |
| `MINOS_RISK_ENGINE__BASELINE_DAYS` | 28 | — |
| `MINOS_RISK_ENGINE__MIN_BASELINE_DAYS` | 7 | — |
| `MINOS_RISK_ENGINE__MEDIA_WEIGHT` | 0.8 | — |
| `MINOS_RISK_ENGINE__SURVEY_WEIGHT` | 0.2 | — |
| `MINOS_RISK_ENGINE__ALERT_COOLDOWN` | 21600 s | — |

### Noticias y RSS

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_CONNECTORS__RSS__USE_GOOGLE_NEWS_SEARCH` | true | — |
| `MINOS_CONNECTORS__RSS__GOOGLE_NEWS_LOCALE` | hl=es-419&gl=MX&ceid=MX:es-419 | — |
| `MINOS_CONNECTORS__RSS__FEEDS` | `[]` | `RSS_FEEDS` |
| `MINOS_CONNECTORS__RSS__POLL_INTERVAL` | 300 s | — |
| `MINOS_CONNECTORS__RSS__USER_AGENT` | un navegador común | — |
| `MINOS_CONNECTORS__RSS__MIN_GAP_PER_HOST` | 1 s | — |

### X

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_CONNECTORS__X__BEARER_TOKEN` | (vacío) | `X_BEARER_TOKEN` |
| `MINOS_CONNECTORS__X__MAX_RESULTS` | 100 | — |
| `MINOS_CONNECTORS__X__POLL_INTERVAL` | 900 s | — |
| `MINOS_CONNECTORS__X__EXCLUDE_RETWEETS` | true | — |

### YouTube

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_CONNECTORS__YOUTUBE__API_KEY` | (vacío) | `YOUTUBE_API_KEY` |
| `MINOS_CONNECTORS__YOUTUBE__REGION_CODE` | MX | — |
| `MINOS_CONNECTORS__YOUTUBE__RELEVANCE_LANGUAGE` | es | — |
| `MINOS_CONNECTORS__YOUTUBE__POLL_INTERVAL` | 1800 s | `YOUTUBE_POLL_INTERVAL` |
| `MINOS_CONNECTORS__YOUTUBE__DAILY_QUOTA` | 10000 | `YOUTUBE_DAILY_QUOTA` |
| `MINOS_CONNECTORS__YOUTUBE__QUOTA_SHARE` | 0.9 | — |

### Bluesky (búsqueda)

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_CONNECTORS__BLUESKY__SERVICE` | https://bsky.social | — |
| `MINOS_CONNECTORS__BLUESKY__IDENTIFIER` | (vacío) | `BLUESKY_IDENTIFIER` |
| `MINOS_CONNECTORS__BLUESKY__APP_PASSWORD` | (vacío) | `BLUESKY_APP_PASSWORD` |
| `MINOS_CONNECTORS__BLUESKY__POLL_INTERVAL` | 300 s | — |

### Bluesky en vivo (Jetstream)

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_CONNECTORS__JETSTREAM__ENABLED` | false | `BLUESKY_LIVE` |
| `MINOS_CONNECTORS__JETSTREAM__URL` | wss://jetstream2.us-east.bsky.network/subscribe | — |
| `MINOS_CONNECTORS__JETSTREAM__PROFILE_API` | https://public.api.bsky.app | — |
| `MINOS_CONNECTORS__JETSTREAM__REPLAY` | 300 s | — |
| `MINOS_CONNECTORS__JETSTREAM__FLUSH_EVERY` | 5 s | — |

### Reddit

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_CONNECTORS__REDDIT__CLIENT_ID` | (vacío) | `REDDIT_CLIENT_ID` |
| `MINOS_CONNECTORS__REDDIT__CLIENT_SECRET` | (vacío) | `REDDIT_CLIENT_SECRET` |
| `MINOS_CONNECTORS__REDDIT__USER_AGENT` | minOS/2.0 | `REDDIT_USER_AGENT` |
| `MINOS_CONNECTORS__REDDIT__SUBREDDITS` | `[]` | — |
| `MINOS_CONNECTORS__REDDIT__POLL_INTERVAL` | 600 s | — |

### Facebook e Instagram

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_CONNECTORS__META__ACCESS_TOKEN` | (vacío) | `META_ACCESS_TOKEN` |
| `MINOS_CONNECTORS__META__GRAPH_URL` | https://graph.facebook.com/v23.0 | — |
| `MINOS_CONNECTORS__META__RECENT_POSTS` | 25 | — |
| `MINOS_CONNECTORS__META__POLL_INTERVAL` | 600 s | — |

### Avisos

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_NOTIFICATIONS__DASHBOARD_URL` | http://localhost:3000 | `DASHBOARD_URL` |
| `MINOS_NOTIFICATIONS__TIMEOUT` | 15 s | — |

### Avisos por correo

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_NOTIFICATIONS__EMAIL__HOST` | (vacío) | `ALERT_EMAIL_HOST` |
| `MINOS_NOTIFICATIONS__EMAIL__PORT` | 587 | `ALERT_EMAIL_PORT` |
| `MINOS_NOTIFICATIONS__EMAIL__USERNAME` | (vacío) | `ALERT_EMAIL_USERNAME` |
| `MINOS_NOTIFICATIONS__EMAIL__PASSWORD` | (vacío) | `ALERT_EMAIL_PASSWORD` |
| `MINOS_NOTIFICATIONS__EMAIL__FROM_ADDR` | (vacío) | `ALERT_EMAIL_FROM` |
| `MINOS_NOTIFICATIONS__EMAIL__TO` | `[]` | `ALERT_EMAIL_TO` |
| `MINOS_NOTIFICATIONS__EMAIL__STARTTLS` | true | — |

### Avisos por webhook

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_NOTIFICATIONS__WEBHOOK__URLS` | `[]` | `ALERT_WEBHOOK_URLS` |
| `MINOS_NOTIFICATIONS__WEBHOOK__SECRET` | (vacío) | `ALERT_WEBHOOK_SECRET` |

### Avisos por WhatsApp

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_NOTIFICATIONS__WHATSAPP__ACCESS_TOKEN` | (vacío) | `WHATSAPP_ACCESS_TOKEN` |
| `MINOS_NOTIFICATIONS__WHATSAPP__PHONE_NUMBER_ID` | (vacío) | `WHATSAPP_PHONE_NUMBER_ID` |
| `MINOS_NOTIFICATIONS__WHATSAPP__TO` | `[]` | `WHATSAPP_TO` |
| `MINOS_NOTIFICATIONS__WHATSAPP__TEMPLATE` | minos_alerta | — |
| `MINOS_NOTIFICATIONS__WHATSAPP__LANGUAGE` | es_MX | — |
| `MINOS_NOTIFICATIONS__WHATSAPP__GRAPH_URL` | https://graph.facebook.com/v23.0 | — |

### Listas negras

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_WATCHLISTS__ENABLED` | true | `WATCHLISTS_ENABLED` |
| `MINOS_WATCHLISTS__SOURCES` | `["ofac-sdn", "ofac-cons", "un-sc", "eu-fsf", "uk-fcdo", "sat-69b", "worldbank"]` | — |
| `MINOS_WATCHLISTS__URLS` | `{}` | — |
| `MINOS_WATCHLISTS__WORLDBANK_API_KEY` | (vacío) | `WORLDBANK_API_KEY` |
| `MINOS_WATCHLISTS__RETRY_AFTER` | 3600 s | — |
| `MINOS_WATCHLISTS__DOWNLOAD_TIMEOUT` | 180 s | — |
| `MINOS_WATCHLISTS__SCREEN_EVERY` | 30 s | — |

### Servicio de análisis (`nlp`)

| Variable | Por omisión | En Docker |
| --- | --- | --- |
| `MINOS_CLAUDE_ENABLED` | 0 | `MINOS_CLAUDE_ENABLED` |
| `MINOS_CLAUDE_MODEL` | claude-haiku-5-5 | `MINOS_CLAUDE_MODEL` |
| `ANTHROPIC_API_KEY` | (vacío) | `ANTHROPIC_API_KEY` |
| `MINOS_CLAUDE_EFFORT` | low | — |
| `MINOS_CLAUDE_BATCH` | 20 | — |
| `MINOS_HIGH_REACH` | 50000 | — |
| `MINOS_USE_TRANSFORMERS` | 0 | — |
| `MINOS_SENTIMENT_MODEL` | cardiffnlp/twitter-xlm-roberta-base-sentiment | — |

### Servidor y tablero

| Variable | Para qué |
| --- | --- |
| `DOMAIN`, `ACME_EMAIL` | Dominio y correo de Let's Encrypt (Caddy) |
| `POSTGRES_PASSWORD` | Contraseña de la base |
| `NEXT_PUBLIC_API_URL` | Dirección de la API; se fija al construir la imagen `web` |

### Respaldos

Las lee `deploy/backup.sh` directo de `.env`; ver [DEPLOY.md](../DEPLOY.md#respaldos).

| Variable | Por omisión |
| --- | --- |
| `BACKUP_S3_ENDPOINT`, `BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY`, `BACKUP_S3_SECRET_KEY` | (vacío) |
| `BACKUP_S3_PROVIDER`, `BACKUP_S3_REGION`, `BACKUP_S3_PREFIX` | DigitalOcean, (vacío), minos |
| `BACKUP_RCLONE_REMOTE` | (vacío); si se llena, reemplaza a `BACKUP_S3_*` |
| `BACKUP_PASSPHRASE` | (vacío); obligatoria para la copia externa |
| `BACKUP_PING_URL` | (vacío) |
| `BACKUP_KEEP_DAYS`, `BACKUP_REMOTE_KEEP_DAYS`, `BACKUP_REMOTE_KEEP_MONTHS` | 14, 30, 12 |
