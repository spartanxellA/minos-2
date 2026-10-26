# minOS 2.0

Monitoreo en tiempo real del riesgo reputacional de personas, empresas, instituciones, áreas de gobierno y países.
Es una reescritura de minOS 1.x (2018), que se hizo con Ionic, Angular, Node.js, Python y MySQL. El backend nuevo
está en Python, igual que los scrapers y el análisis de texto, y el tablero en Next.js.

## Piezas

| Carpeta | Qué es | Tecnología |
| --- | --- | --- |
| `backend/minos/domain` | Objetivos, menciones, cálculo de riesgo (cuestionario, medios, IRR, alertas) | Python puro |
| `backend/minos/connectors` | Conectores de fuentes (los scrapers): Noticias/RSS (Google Noticias + feeds), X (API v2), YouTube (Data API v3), Bluesky (búsqueda y en vivo por Jetstream), Reddit, páginas propias de Facebook e Instagram, demo | httpx, feedparser, websockets |
| `backend/minos` | API REST y WebSocket del tablero (`/ws/targets/{id}`) | FastAPI, SQLAlchemy 2, PostgreSQL |
| `backend/minos/worker.py` | Proceso aparte con la ingesta (conectores) y el motor de riesgo; escala con varias réplicas | asyncio, Redis |
| `nlp/` | Servicio de análisis: sentimiento para todo, Claude solo para lo negativo o de alto alcance | FastAPI |
| `web/` | Tablero en vivo y cuestionario de riesgo | Next.js, ECharts |
| `data/surveys.json` | Los 2 cuestionarios de minOS 1.6 (107 preguntas, opciones y pesos), migrados tal cual | JSON |

## Cómo fluye una mención

1. Cada conector trae lo nuevo desde su cursor (`connector_cursors`) cuando le toca según su intervalo.
2. `is_relevant` descarta homónimos y términos excluidos; se deduplica por id externo y por huella del texto.
3. El lote se analiza una sola vez (servicio `nlp`, o el mismo diccionario si no responde) y se guarda.
4. La ingesta pide el recálculo por la cola (Redis Stream `minos:recompute`, grupo `risk-engine`: cada pedido lo
   atiende una sola réplica) y avisa de las menciones nuevas.
5. El motor de riesgo recalcula el IRR del objetivo, guarda el punto de la serie y evalúa alertas.
6. Los eventos `mentionsAdded`, `riskUpdated` y `alertRaised` salen por Redis pub/sub (`minos:live`); cada instancia
   de la API los reenvía a sus WebSocket.

Con varias réplicas de workers, un candado en Redis por objetivo y fuente evita consultar dos veces lo mismo, y otro
evita que dos réplicas hagan el recálculo completo periódico a la vez.

Modos (`MINOS_ROLE`):

- `all` (por omisión): la API corre también la ingesta y el motor de riesgo. Sin `MINOS_REDIS_URL` todo va en memoria
  dentro de un proceso; sirve para desarrollo y pruebas.
- `api`: la API solo sirve datos y WebSocket. Los workers corren con `python -m minos.worker`, que exige
  `MINOS_REDIS_URL`.

## Fuentes

Cada conector se apaga solo si le falta su llave (variables en `.env.example`).

| Fuente | Qué trae | Necesita |
| --- | --- | --- |
| Noticias | Google Noticias por nombre y los feeds RSS que se agreguen | nada |
| X | Búsqueda reciente (7 días) de la API v2 | `X_BEARER_TOKEN` (plan de pago de X) |
| YouTube | Videos por nombre | `YOUTUBE_API_KEY` |
| Bluesky | Búsqueda cada 5 min | cuenta con contraseña de aplicación |
| Bluesky en vivo | Todas las publicaciones de la red al momento (Jetstream), filtradas por los objetivos; una sola réplica de workers mantiene la conexión | `BLUESKY_LIVE=true` |
| Reddit | Publicaciones (la API no permite buscar comentarios), en todo Reddit o en los subreddits de `MINOS_CONNECTORS__REDDIT__SUBREDDITS` | app OAuth de Reddit |
| Facebook | Comentarios y publicaciones de visitantes en la página del objetivo, y publicaciones que la etiquetan | `META_ACCESS_TOKEN` y `handles.facebook` = id de la página |
| Instagram | Comentarios en la cuenta del objetivo y publicaciones que la etiquetan | `META_ACCESS_TOKEN` y `handles.instagram` = id de la cuenta profesional |

Facebook e Instagram no permiten buscar menciones públicas: solo se lee lo que pasa en las cuentas propias del
objetivo, con un token de Meta Business que tenga acceso a ellas. Esos comentarios cuentan aunque no nombren al
objetivo. Las cuentas se guardan en `handles` del objetivo (`PUT /api/targets/{id}`).

## Cuentas e inicio de sesión

El tablero, la API y el WebSocket piden iniciar sesión con correo y contraseña. La sesión va en una cookie HttpOnly
(el JavaScript del tablero no la ve), dura 7 días y se puede cerrar desde el tablero. Roles:

| Rol | Puede |
| --- | --- |
| Lector | Ver el tablero, las menciones, las alertas y los cuestionarios contestados |
| Analista | Además, agregar y editar objetivos y contestar el cuestionario |
| Administrador | Además, borrar objetivos y administrar cuentas (botón "Usuarios") |

El primer administrador se crea con `ADMIN_EMAIL` y `ADMIN_PASSWORD` en `.env` (solo si todavía no hay cuentas), o
desde la terminal:

```bash
docker compose run --rm migrate python -m minos.users add tu@correo.com --role admin --name "Tu nombre"
docker compose run --rm migrate python -m minos.users password tu@correo.com   # olvidó su contraseña o quedó bloqueada
```

Seguridad: contraseñas con scrypt y mínimo 10 caracteres; tras 5 intentos fallidos la cuenta se bloquea 15 minutos;
desactivar una cuenta o cambiarle la contraseña cierra sus sesiones al momento; las peticiones que cambian datos y el
WebSocket se rechazan si vienen de otro sitio. Con `AUTH_MODE=off` no se pide contraseña, solo en development.

## Avisos de alertas

Las alertas se ven en vivo en el tablero. Además se avisan por los canales configurados (vacío = apagado):

| Canal | Variables | Notas |
| --- | --- | --- |
| Navegador | botón "Activar avisos" del tablero | Aviso del sistema para el objetivo que se está viendo, con la pestaña abierta. |
| Correo | `ALERT_EMAIL_*` (SMTP) | STARTTLS en 587, TLS directo en 465. |
| Webhook | `ALERT_WEBHOOK_URLS`, `ALERT_WEBHOOK_SECRET` | JSON con `text` (lo entienden los webhooks entrantes de Slack y Teams) y `alert` con los datos. Con secreto, firma `X-Minos-Signature: sha256=HMAC`. |
| WhatsApp | `WHATSAPP_*` | WhatsApp Cloud API. Fuera de una conversación abierta Meta solo permite plantillas aprobadas: hay que crear la plantilla `minos_alerta` con tres variables, por ejemplo "Alerta minOS para {{1}}: {{2}}. {{3}}". |

Cada aviso trae el objetivo, la alerta, el índice actual, el enlace a la mención si la hay y el enlace al tablero
(`/?target=<id>`, con la dirección de `MINOS_NOTIFICATIONS__DASHBOARD_URL`). Un cambio de tendencia o un pico de
negativas se registra y avisa una sola vez cada 6 horas por objetivo (`MINOS_RISK_ENGINE__ALERT_COOLDOWN`), aunque
la condición siga activa en cada recálculo. Un canal que falla queda en el registro y no frena a los demás.

## Índice de Riesgo Reputacional (IRR, 0–100)

- Medios: `M = 100 × (0.5 N + 0.3 S + 0.2 V)`. N es la negatividad ponderada por alcance, S las acusaciones graves
  y V el volumen anómalo (z/3 contra 28 días, apagado los primeros 7 días).
- Cuestionario: la fórmula exacta de minOS 1.6 (`risk-survey.ts`), con pruebas de paridad. Se contesta en el
  tablero (tarjeta "Cuestionario de riesgo"), por secciones y precargado con las últimas respuestas. Como en 1.6,
  hay que contestar todas las preguntas: una sin contestar bajaría la sección por debajo de 0. Al guardar se
  recalcula el IRR y el tablero lo recibe en vivo. Historial: `GET /api/targets/{id}/survey-responses`.
- `IRR = 0.6 M + 0.4 C`; sin cuestionario, `IRR = M`. Umbrales heredados: ≤ 25 bajo, ≤ 50 medio, > 50 alto.
- Los pesos se configuran con `MINOS_RISK_ENGINE__MEDIA_WEIGHT` y `MINOS_RISK_ENGINE__SURVEY_WEIGHT`. Son un punto
  de partida para calibrar con datos históricos.

## Correr en local

Con Docker:

```bash
cp .env.example .env   # llena las llaves que tengas
docker compose up --build -d
```

Levanta siete servicios: `db` (PostgreSQL 16 con TimescaleDB), `redis`, `migrate` (aplica las migraciones
pendientes y termina), `nlp`, `api` (`MINOS_ROLE=api`, arranca cuando `migrate` terminó bien), `worker`
(conectores y motor de riesgo) y `web`. Para más réplicas de workers: `docker compose up -d --scale worker=3`. El tablero queda en http://localhost:3000.
`NEXT_PUBLIC_API_URL` se fija al construir la imagen `web`: para un servidor, cámbiala en `docker-compose.yml` por
la URL pública de la API.

Sin Docker (Python 3.12+, PostgreSQL local con usuario, clave y base `minos`):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e nlp -e "backend[dev]"
python -m minos.migrate                         # crea o actualiza las tablas
uvicorn minos_nlp.app:app --port 8000 &
cd backend && MINOS_DEMO__ENABLED=true MINOS_NLP_URL=http://localhost:8000 uvicorn minos.main:app --port 5080
cd web && npm install && npm run dev            # http://localhost:3000
```

## Migraciones

El esquema vive en `backend/minos/migrations` (Alembic) y viaja dentro del paquete, así que la imagen de la API no
necesita archivos extra.

```bash
python -m minos.migrate                          # aplica las pendientes (upgrade head)
python -m minos.migrate revision -m "qué cambia"  # genera una nueva a partir de los modelos de minos/db.py
python -m minos.migrate downgrade                # revierte la última
python -m minos.migrate current                  # muestra la versión de la base
```

Revisa siempre la migración generada antes de subirla. Con TimescaleDB disponible, `risk_snapshots` es una
hypertable particionada por semana; en un PostgreSQL sin la extensión queda como tabla normal y todo funciona igual.

La configuración va en variables `MINOS_*` (secciones con `__`, duraciones en segundos). Por ejemplo
`MINOS_DATABASE_URL`, `MINOS_CONNECTORS__X__BEARER_TOKEN` o `MINOS_INGESTION__TICK=30`; la lista completa está en
`backend/minos/config.py`. Con `MINOS_DEMO__ENABLED=true` la fuente `demo` genera menciones sintéticas para ver el
tablero moverse sin llaves de API.

## Pruebas

```bash
cd backend && pytest     # dominio, conectores (HTTP simulado), cuestionarios, API + pipeline + WebSocket (SQLite)
cd nlp && pytest
cd web && npm run typecheck
```

Con `MINOS_TEST_POSTGRES_URL=postgresql+asyncpg://...` (una base de prueba, se borra en cada corrida) también se
prueban las migraciones (que coincidan con los modelos, que suban y bajen, la hypertable) y la API sobre PostgreSQL
migrado. Las pruebas del bus usan fakeredis, o un Redis real con `MINOS_TEST_REDIS_URL=redis://...`. CI lo hace contra TimescaleDB y Redis, y además construye las imágenes y levanta el stack con `docker compose`.

## Pendiente

- Políticas de retención y compresión de TimescaleDB cuando haya volumen real.
- Editar las cuentas propias (`handles`) de un objetivo desde el tablero; hoy se hace por la API.
- Cuestionario de perfil (PDSurvey) en el tablero, reportes PDF, app móvil con notificaciones push.
- Destinatarios de avisos por objetivo; hoy son los mismos para todos.
- Recuperar el scraper (Node.js/Python) y el esquema MySQL originales para comparar resultados con la versión anterior.
