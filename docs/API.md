# API de minOS 2.0

REST con JSON bajo `/api` y un WebSocket por objetivo. Los campos van en camelCase y las fechas en ISO 8601 (UTC). Esta
página lista todas las rutas; los esquemas exactos los genera FastAPI en `/docs` y `/openapi.json` del contenedor de la
API (en local, http://localhost:5080/docs). Caddy no los expone en el servidor.

## Reglas generales

- **Sesión**: cookie `minos_session` (HttpOnly, SameSite=Lax) que da `POST /api/auth/login`. Todas las rutas la piden,
  salvo `/health`, el inicio y el cierre de sesión. Sin sesión: `401`.
- **Rol**: lector < analista < administrador. Con un rol menor al pedido: `403`. "Lector" significa cualquier cuenta.
- **Origen**: una petición que cambia datos desde otro sitio se rechaza con `403`.
- **Actividad**: solo `GET /api/auth/me` y `POST /api/auth/activity` cuentan como actividad de la persona; las demás
  consultas no evitan el cierre por inactividad.
- **Errores**: `{"detail": "mensaje en español"}`. `400` o `422` datos inválidos, `404` no existe, `409` conflicto
  (nombre repetido, ya dado de baja), `413` archivo muy grande, `429` demasiados intentos (con `Retry-After`).
- **Valores**: `kind` es `Person`, `Company`, `Institution`, `GovernmentArea` o `Country`; `sentiment` es `negative`,
  `neutral` o `positive`; `source` es `rss`, `x`, `youtube`, `bluesky`, `reddit`, `facebook`, `instagram` o `demo`
  (Bluesky en vivo guarda sus menciones como `bluesky`).

## Sesión y cuentas

| Ruta | Rol | Qué hace |
| --- | --- | --- |
| `POST /api/auth/login` | — | `{email, password}`; abre la sesión |
| `POST /api/auth/logout` | — | Cierra la sesión; `{"reason": "user" \| "idle"}` opcional |
| `GET /api/auth/me` | Lector | Cuenta, rol, `idleTimeoutSeconds` y `language` |
| `POST /api/auth/activity` | Lector | El tablero avisa que la persona lo está usando (a lo más una vez por minuto) |
| `PUT /api/auth/preferences` | Lector | `{language: "es" \| "en" \| "fr"}` |
| `POST /api/auth/password` | Lector | `{currentPassword, newPassword}`; cierra las demás sesiones de la cuenta |
| `GET /api/users` | Administrador | Cuentas |
| `POST /api/users` | Administrador | `{email, name, role, password}`; `role` es `viewer`, `analyst` o `admin` |
| `PATCH /api/users/{id}` | Administrador | Cambia `name`, `role`, `active` o `password` (quita también los bloqueos) |
| `DELETE /api/users/{id}` | Administrador | Borra la cuenta; no la propia ni la del último administrador activo |

## Objetivos

| Ruta | Rol | Qué hace |
| --- | --- | --- |
| `GET /api/targets?status=active\|inactive\|all` | Lector | Todos, por nombre (por omisión `all`) |
| `GET /api/targets/search` | Lector | Búsqueda del selector: `q`, `kind`, `status` (`active`), `limit` (50, máximo 200), `offset`. Da `items`, `total` y `kinds` (conteo por tipo) |
| `GET /api/targets/{id}` | Lector | Un objetivo |
| `POST /api/targets` | Analista | Alta |
| `PUT /api/targets/{id}` | Analista | Cambia todos los datos; si cambia lo que se busca, los cursores vuelven a empezar |
| `POST /api/targets/{id}/deactivate` | Analista | Baja lógica, `{reason}` obligatorio |
| `POST /api/targets/{id}/reactivate` | Analista | Reactiva |
| `DELETE /api/targets/{id}` | Administrador | Borrado definitivo, solo de uno dado de baja |

Cuerpo de alta y cambio: `name`, `kind`, `aliases`, `keywords`, `excludedTerms`, `handles` (`{"facebook": "id"}`),
`birthDate` (`AAAA` o `AAAA-MM-DD`), `nationality`, `identifiers` (`{"rfc": "…", "curp": "…", "pasaporte": "…"}`).

## Menciones, riesgo y fuentes

| Ruta | Rol | Qué hace |
| --- | --- | --- |
| `GET /api/targets/{id}/mentions` | Lector | `source`, `sentiment`, `limit` (50, máximo 500) |
| `POST /api/mentions/{id}/sentiment` | Analista | `{sentiment}`; corrige, recalcula el índice y avisa en vivo |
| `GET /api/targets/{id}/risk?hours=168` | Lector | Serie del IRR (máximo un año) |
| `GET /api/targets/{id}/risk/latest` | Lector | Último cálculo |
| `GET /api/targets/{id}/breakdown?hours=24` | Lector | Sentimiento por fuente, autores de mayor alcance y temas del análisis (máximo 90 días) |
| `GET /api/targets/{id}/alerts` | Lector | Las 50 alertas más recientes |
| `GET /api/targets/{id}/connectors` | Lector | Cursor, última corrida y último error por fuente |
| `GET /api/sources` | Lector | Estado de cada fuente (errores y avisos por separado) y de cada canal de avisos |
| `GET /api/targets/{id}/topics` | Lector | Nube de temas: `days` (30, máximo 365), `source`, `sentiment`, `limit` (80, de 10 a 150) |
| `GET /api/targets/{id}/geo` | Lector | Mapa: `days` (30, máximo 365), `source`, `basis=all\|origin\|text` |
| `POST /api/targets/{id}/geo/locate` | Analista | Ubica las menciones guardadas antes del mapa |

El texto técnico de los errores de fuentes solo lo recibe un administrador; los demás roles, una explicación corta.

## Análisis

| Ruta | Rol | Qué hace |
| --- | --- | --- |
| `GET /api/analytics/mentions` | Lector | Todos los sujetos: `granularity=month\|year`, `since`, `until` (`AAAA` o `AAAA-MM`), `kind`, `source`, `top` (10, máximo 50), `includeInactive` |
| `GET /api/analytics/targets/{id}/history` | Lector | Un objetivo: `granularity=day\|month\|year`, `days` (30, de 2 a 180; solo por día), `since`, `until`, `source` |

Sin `since`: los últimos 12 meses, o desde el año de la primera mención. Máximo 240 periodos. Los cortes se hacen en la
zona `MINOS_TIMEZONE`.

## Cuestionarios

| Ruta | Rol | Qué hace |
| --- | --- | --- |
| `GET /api/surveys` | Lector | Cuestionarios disponibles |
| `GET /api/surveys/{id}` | Lector | Secciones, preguntas y opciones |
| `GET /api/targets/{id}/survey-responses` | Lector | Historial: `surveyId`, `limit` (10, máximo 100) |
| `POST /api/targets/{id}/survey-responses` | Analista | `{surveyId, answers: {pregunta: "A"}}`; recalcula el IRR |

## Listas negras

| Ruta | Rol | Qué hace |
| --- | --- | --- |
| `GET /api/targets/{id}/screening` | Lector | Estado y coincidencias de un objetivo |
| `GET /api/screening/matches` | Lector | Coincidencias vigentes de todos: `status=pending\|confirmed\|dismissed`, `limit` (200, máximo 500) |
| `POST /api/screening/matches/{id}/review` | Analista | `{decision: "confirmed" \| "dismissed" \| "pending", note}` |
| `GET /api/screening/matches/{id}/history` | Lector | Historial del registro en su lista |
| `GET /api/watchlists` | Lector | Listas oficiales y propias, con su estado |
| `POST /api/watchlists/custom` | Administrador | `{name, category, csv, mode, fileName}` |
| `POST /api/watchlists/custom/file` | Administrador | El archivo en el cuerpo (hasta 300 MB): `name`, `category`, `mode`, `fileName` en la URL |
| `DELETE /api/watchlists/custom/{slug}` | Administrador | Borra una lista propia |
| `GET /api/watchlists/custom/{slug}/uploads` | Lector | Historial de cargas, `limit` (50, máximo 200) |
| `GET /api/watchlists/uploads/{id}/changes.csv` | Analista | Detalle de una carga |

`category` es `pep`, `sanctions`, `tax`, `debarment` u `other`; `mode` es `full` (reemplaza) o `update` (altas y cambios).

## Auditoría y salud

| Ruta | Rol | Qué hace |
| --- | --- | --- |
| `GET /api/audit` | Administrador | Eventos: `action` (exacta, o prefijo como `auth.`), `actor`, `actorId`, `entityType`, `entityId`, `success`, `since`, `until`, `q`, `limit` (100, máximo 500), `before` |
| `GET /api/audit/export.csv` | Administrador | Lo mismo en CSV, hasta 50,000 filas; la descarga queda en la bitácora |
| `GET /health` | — | `{"status": "ok"}` |

## Canal en vivo

`GET /ws/targets/{id}` (WebSocket, con la cookie de sesión). Los mensajes son `{"event": "…", "data": …}`:

| Evento | Cuándo | Contenido |
| --- | --- | --- |
| `mentionsAdded` | Llegan menciones | Hasta 20, las más recientes |
| `mentionUpdated` | Un analista corrige un sentimiento | La mención |
| `riskUpdated` | Cada recálculo | El punto nuevo del IRR |
| `alertRaised` | Alerta de riesgo o de listas | La alerta |
| `screeningUpdated` | Cambia la revisión en listas | Estado y coincidencias del objetivo |

El cliente manda un ping cada 25 s. Los pings no cuentan como actividad; a lo más cada minuto la API revisa que la
sesión siga abierta y, si no, cierra con código 1008.

## Servicio de análisis (`nlp`)

Interno: en el servidor no tiene puerto público. `POST /v1/analyze` con
`{target, items: [{text, language, reach}], examples: [{text, sentiment}]}` (hasta 500 textos y 30 ejemplos) da
`{results: [{sentiment, score, severeAccusation, topic, summary, analyzer}]}`. `GET /health` dice qué modelo usa y si
Claude está encendido.
