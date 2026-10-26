# minOS 2.0

Monitoreo en tiempo real del riesgo reputacional de personas, empresas, instituciones, áreas de gobierno y países.
Es una reescritura de minOS 1.x (2018), que se hizo con Ionic, Angular, Node.js, Python y MySQL. El backend nuevo
está en Python, igual que los scrapers y el análisis de texto, y el tablero en Next.js.

## Piezas

| Carpeta | Qué es | Tecnología |
| --- | --- | --- |
| `backend/minos/domain` | Objetivos, menciones, cálculo de riesgo (cuestionario, medios, IRR, alertas) | Python puro |
| `backend/minos/connectors` | Conectores de fuentes (los scrapers): Noticias/RSS (Google Noticias + feeds), X (API v2), YouTube (Data API v3), Bluesky, demo | httpx, feedparser |
| `backend/minos` | API REST, WebSocket del tablero (`/ws/targets/{id}`), ingesta y motor de riesgo como tareas en segundo plano | FastAPI, SQLAlchemy 2, PostgreSQL |
| `nlp/` | Servicio de análisis: sentimiento para todo, Claude solo para lo negativo o de alto alcance | FastAPI |
| `web/` | Tablero en vivo | Next.js, ECharts |
| `data/surveys.json` | Los 2 cuestionarios de minOS 1.6 (107 preguntas, opciones y pesos), migrados tal cual | JSON |

## Cómo fluye una mención

1. Cada conector trae lo nuevo desde su cursor (`connector_cursors`) cuando le toca según su intervalo.
2. `is_relevant` descarta homónimos y términos excluidos; se deduplica por id externo y por huella del texto.
3. El lote se analiza una sola vez (servicio `nlp`, o el mismo diccionario si no responde) y se guarda.
4. El motor de riesgo recalcula el IRR del objetivo, guarda el punto de la serie, evalúa alertas y lo empuja por WebSocket.

## Índice de Riesgo Reputacional (IRR, 0–100)

- Medios: `M = 100 × (0.5 N + 0.3 S + 0.2 V)`. N es la negatividad ponderada por alcance, S las acusaciones graves
  y V el volumen anómalo (z/3 contra 28 días, apagado los primeros 7 días).
- Cuestionario: la fórmula exacta de minOS 1.6 (`risk-survey.ts`), con pruebas de paridad.
- `IRR = 0.6 M + 0.4 C`; sin cuestionario, `IRR = M`. Umbrales heredados: ≤ 25 bajo, ≤ 50 medio, > 50 alto.
- Los pesos se configuran con `MINOS_RISK_ENGINE__MEDIA_WEIGHT` y `MINOS_RISK_ENGINE__SURVEY_WEIGHT`. Son un punto
  de partida para calibrar con datos históricos.

## Correr en local

Con Docker:

```bash
cp .env.example .env   # llena las llaves que tengas
docker compose up --build
```

Sin Docker (Python 3.12+, PostgreSQL local con usuario, clave y base `minos`):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e nlp -e "backend[dev]"
uvicorn minos_nlp.app:app --port 8000 &
cd backend && MINOS_DEMO__ENABLED=true MINOS_NLP_URL=http://localhost:8000 uvicorn minos.main:app --port 5080
cd web && npm install && npm run dev            # http://localhost:3000
```

La configuración va en variables `MINOS_*` (secciones con `__`, duraciones en segundos). Por ejemplo
`MINOS_DATABASE_URL`, `MINOS_CONNECTORS__X__BEARER_TOKEN` o `MINOS_INGESTION__TICK=30`; la lista completa está en
`backend/minos/config.py`. Con `MINOS_DEMO__ENABLED=true` la fuente `demo` genera menciones sintéticas para ver el
tablero moverse sin llaves de API. Fuera de `MINOS_ENV=development` la API exige `MINOS_AUTH__AUTHORITY` (OIDC) y
no arranca sin él.

## Pruebas

```bash
cd backend && pytest     # dominio, conectores (HTTP simulado), cuestionarios, API + pipeline + WebSocket (SQLite)
cd nlp && pytest
cd web && npm run typecheck
```

## Pendiente

- Migraciones con Alembic (hoy `create_all` al arrancar) e hypertable de TimescaleDB para `risk_snapshots`.
- Redis (Streams para la cola y pub/sub para el WebSocket) para separar conectores y API en procesos distintos.
  Hoy todo corre en un proceso y `MINOS_RUN_WORKERS=false` deja la API solo sirviendo datos.
- Conectores fase 2: Reddit, páginas propias de Facebook/Instagram; Bluesky por Jetstream (stream).
- Cuestionario en el tablero, reportes PDF, notificaciones push/correo/WhatsApp, app móvil.
- Recuperar el scraper (Node.js/Python) y el esquema MySQL originales para comparar resultados con la versión anterior.
