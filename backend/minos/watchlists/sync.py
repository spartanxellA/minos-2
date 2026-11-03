"""Descarga de las listas oficiales y carga de las propias.

Cada lista se descarga según su frecuencia (OFAC cada 6 h, las demás cada día). Si el archivo no cambió (misma
huella SHA-256) no se procesa. Si cambió, se agregan los registros nuevos, se actualizan los modificados y se borran
los que salieron; el revisor de objetivos lo nota porque cambia la versión de la lista.
"""
import asyncio
import hashlib
import itertools
import json
import logging
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import delete, insert, select, update

from .. import db
from ..bus import Bus
from ..config import WatchlistSettings
from ..connectors.base import redact_secrets
from ..domain.screening import WatchlistRecord, ascii_fold
from .sources import LOOKS_LIKE_CURP, LOOKS_LIKE_DATE, LOOKS_LIKE_RFC, OFFICIAL_SOURCES, OfficialSource

log = logging.getLogger(__name__)

TICK_SECONDS = 60
BATCH = 2000


def record_fingerprint(r: WatchlistRecord) -> str:
    payload = [r.kind.value, r.name, list(r.aliases), list(r.birth_dates), list(r.nationalities), list(r.identifiers),
               list(r.programs), r.listed_on, r.status, r.url, r.notes]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def _entry_row(slug: str, ext: str, r: WatchlistRecord) -> dict:
    return {
        "source": slug, "external_id": ext, "kind": r.kind.value, "name": r.name[:500],
        "aliases": [a[:500] for a in r.aliases], "birth_dates": list(r.birth_dates),
        "nationalities": list(r.nationalities), "identifiers": list(r.identifiers), "programs": list(r.programs),
        "listed_on": (r.listed_on or None) and r.listed_on[:32], "status": (r.status or None) and r.status[:64],
        "url": r.url, "notes": r.notes, "fingerprint": record_fingerprint(r),
    }


async def batches(records: Iterable[WatchlistRecord], size: int = BATCH) -> AsyncIterator[list[WatchlistRecord]]:
    """Lee los registros por tandas en otro hilo: una lista de cientos de miles no se carga completa en memoria ni
    detiene al servidor mientras se lee."""
    it = iter(records)
    while batch := await asyncio.to_thread(lambda: list(itertools.islice(it, size))):
        yield batch


# Campos que se comparan para el historial de cada registro (en este orden se muestran).
TRACKED_FIELDS = ("status", "name", "programs", "birth_dates", "identifiers", "nationalities", "aliases")


@dataclass
class StoreCounts:
    """Resultado de una carga. changed incluye los cambios de estatus (status_changed es una parte de changed)."""
    rows: int = 0
    added: int = 0
    changed: int = 0
    status_changed: int = 0
    unchanged: int = 0
    removed: int = 0
    entries: int = 0
    # Registros que ya estaban con otra llave (cambio de cargo o llave de una versión anterior) y se reconocieron.
    rekeyed: int = 0

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.entries, self.added, self.changed, self.removed


def _is_doc(value: str) -> bool:
    return bool(LOOKS_LIKE_RFC.fullmatch(value) or LOOKS_LIKE_CURP.fullmatch(value))


def _person_key(name: str, birth: str) -> str:
    """Nombre sin acentos + fecha de nacimiento: el inicio de la llave de las filas PEP sin RFC ni CURP."""
    return f"{ascii_fold(name)}|{birth}"


def _diff(old, row: dict) -> dict:
    out = {}
    for f in TRACKED_FIELDS:
        before, after = getattr(old, f), row[f]
        if isinstance(before, list) or isinstance(after, list):
            before, after = list(before or []), list(after or [])
        if before != after:
            out[f] = [before, after]
    return out


async def store_entries(session, slug: str, records: Iterable[WatchlistRecord] | AsyncIterator[list[WatchlistRecord]],
                        *, mode: str = "full", upload_id: int | None = None) -> StoreCounts:
    """Guarda los registros de una lista.

    full: deja en la base exactamente los registros recibidos (los que no vienen se borran).
    update: archivo de actualizaciones; agrega los nuevos y actualiza los que cambiaron, sin borrar a nadie.

    La llave de cada fila es RFC/CURP + cargo, o nombre + fecha de nacimiento + cargo si no trae documentos. Si la
    llave no existe pero hay exactamente una persona con el mismo RFC/CURP (o, sin documentos, el mismo nombre y
    fecha) que aún no apareció en el archivo, es esa persona con otro cargo: toma la llave nueva y sus coincidencias
    e historial la siguen. Sin documentos ni fecha no se adivina: puede ser un homónimo, y el archivo de
    actualizaciones ya marca con estatus 0 el cargo que se deja.

    Con upload_id, cada alta, cambio y retiro queda en el historial (watchlist_changes). En la primera carga de una
    lista no se anotan las altas: serían cientos de miles de filas que solo dicen "estaba en la primera lista".
    """
    E, C = db.WatchlistEntry, db.WatchlistChange
    existing: dict[str, tuple[int, str]] = {}
    # Para reconocer a una persona que ya estaba con otra llave: por RFC/CURP, o por nombre + fecha de nacimiento si
    # no tiene documentos. Solo en listas propias (las oficiales traen su propio id).
    by_doc: dict[str, list[str]] = {}
    by_person: dict[str, list[str]] = {}
    cargo_of: dict[str, list[str]] = {}
    result = await session.stream(select(E.id, E.external_id, E.fingerprint, E.name, E.birth_dates, E.identifiers,
                                         E.programs).where(E.source == slug).execution_options(yield_per=5000))
    async for part in result.partitions():
        for id_, ext, fp, name, births, ids, programs in part:
            existing[ext] = (id_, fp)
            if upload_id is None or not (births or ids):
                continue
            values = [*(ids or []), *(births or [])]  # las llaves viejas traen la fecha y el RFC invertidos
            docs = [v for v in values if _is_doc(v)]
            for d in docs:
                by_doc.setdefault(d, []).append(ext)
            birth = next((v for v in values if LOOKS_LIKE_DATE.fullmatch(v)), "")
            if birth and not docs:
                by_person.setdefault(_person_key(name, birth), []).append(ext)
            if docs or birth:
                cargo_of[ext] = list(programs or [])
    log_added = upload_id is not None and bool(existing)
    renames: list[tuple[str, str]] = []
    now = datetime.now(UTC)
    seen: set[str] = set()
    counts = StoreCounts()
    chunks = records if hasattr(records, "__aiter__") else batches(records)
    async for chunk in chunks:
        inserts, updates, history = [], [], []
        for r in chunk:
            counts.rows += 1
            ext = r.external_id[:200]
            if ext not in existing and ext not in seen and (by_doc or by_person):
                if r.identifiers:
                    candidates = {c for d in r.identifiers for c in by_doc.get(d, ())}
                elif r.birth_dates:
                    candidates = set(by_person.get(_person_key(r.name, r.birth_dates[0]), ()))
                else:
                    # Sin documentos ni fecha, el nombre solo no basta: puede ser un homónimo.
                    candidates = set()
                candidates = [c for c in candidates if c in existing and c not in seen]
                if len(candidates) > 1:
                    # Varios cargos de la misma persona: es el que tiene el mismo cargo.
                    candidates = [c for c in candidates if cargo_of.get(c) == list(r.programs)]
                if len(candidates) == 1:
                    # Es la misma persona con otra llave (cambió de cargo, o una llave de la versión anterior): toma la
                    # llave nueva y sus coincidencias e historial la siguen.
                    old_ext = candidates[0]
                    existing[ext] = existing.pop(old_ext)
                    renames.append((old_ext, ext))
            if ext in seen:
                continue
            seen.add(ext)
            row = _entry_row(slug, ext, r)
            if ext not in existing:
                inserts.append(row)
                if log_added:
                    history.append({"source": slug, "external_id": ext, "name": row["name"], "change": "added",
                                    "fields": {"status": [None, row["status"]]} if row["status"] else {}})
            elif existing[ext][1] != row["fingerprint"]:
                updates.append((existing[ext][0], row))
            else:
                counts.unchanged += 1
        if renames:
            for old_ext, new_ext in renames:
                await session.execute(update(E).where(E.source == slug, E.external_id == old_ext)
                                      .values(external_id=new_ext))
                for model in (db.ScreeningMatch, C):
                    await session.execute(update(model).where(model.source == slug, model.external_id == old_ext)
                                          .values(external_id=new_ext))
            counts.rekeyed += len(renames)
            renames.clear()
        if updates:
            cols = [getattr(E, f) for f in TRACKED_FIELDS]
            olds = {o.id: o for o in (await session.execute(
                select(E.id, *cols).where(E.id.in_([i for i, _ in updates])))).all()}
            for id_, row in updates:
                fields = _diff(olds[id_], row) if id_ in olds else {}
                counts.changed += 1
                counts.status_changed += "status" in fields
                if upload_id is not None and fields:
                    history.append({"source": slug, "external_id": row["external_id"], "name": row["name"],
                                    "change": "status" if "status" in fields else "changed", "fields": fields})
            for id_, row in updates:
                await session.execute(update(E).where(E.id == id_).values(**row))
        if inserts:
            counts.added += len(inserts)
            await session.execute(insert(E), inserts)
        if history:
            await session.execute(insert(C), [dict(h, upload_id=upload_id, at=now) for h in history])
    if mode == "full":
        gone = [id_ for ext, (id_, _) in existing.items() if ext not in seen]
        for i in range(0, len(gone), BATCH):
            ids = gone[i:i + BATCH]
            if upload_id is not None:
                rows = (await session.execute(select(E.external_id, E.name, E.status).where(E.id.in_(ids)))).all()
                await session.execute(insert(C), [
                    {"upload_id": upload_id, "source": slug, "external_id": ext, "name": name, "change": "removed",
                     "fields": {"status": [st, None]} if st else {}, "at": now} for ext, name, st in rows])
            await session.execute(delete(E).where(E.id.in_(ids)))
        counts.removed = len(gone)
        counts.entries = len(seen)
    else:
        counts.entries = len(existing) + counts.added
    return counts


async def save_list(database: db.Database, slug: str,
                    records: Iterable[WatchlistRecord] | AsyncIterator[list[WatchlistRecord]], version: str,
                    now: datetime, *, official: OfficialSource | None = None, name: str | None = None,
                    category: str | None = None, uploaded_by: str | None = None, mode: str = "full",
                    file_name: str | None = None) -> tuple[StoreCounts, int | None]:
    """Guarda una lista. Las propias dejan registro de la carga y del historial; devuelve (conteos, id de la carga).

    En una actualización la versión de la lista cambia solo si algo cambió: así los objetivos se vuelven a revisar
    (y las coincidencias confirmadas toman el estatus nuevo) sin trabajo de más cuando el archivo no trae novedades.
    """
    async with database.session() as session:
        row = await session.get(db.WatchlistSource, slug)
        if row is None:
            row = db.WatchlistSource(slug=slug, name=name or slug, category=category or "other",
                                     custom=official is None, entry_count=0)
            session.add(row)
        if official is not None:
            row.name, row.category = official.name, official.category
        else:
            row.name, row.category, row.uploaded_by = name or row.name, category or row.category, uploaded_by
        await session.flush()
        upload = None
        if official is None:
            upload = db.WatchlistUpload(source=slug, mode=mode, file_name=(file_name or None) and file_name[:255],
                                        at=now, uploaded_by=uploaded_by)
            session.add(upload)
            await session.flush()
        counts = await store_entries(session, slug, records, mode=mode, upload_id=upload.id if upload else None)
        touched = counts.added or counts.changed or counts.removed
        if mode == "update":
            if touched:
                row.version = hashlib.sha256(f"{row.version or ''}|{version}".encode()).hexdigest()
                row.last_changed_at = now
        else:
            row.version, row.last_changed_at = version, now
        row.entry_count = counts.entries
        row.last_checked_at, row.last_error = now, None
        if upload is not None:
            for f in ("rows", "added", "changed", "status_changed", "unchanged", "removed", "entries"):
                setattr(upload, f, getattr(counts, f))
        upload_id = upload.id if upload else None
        await session.commit()
    log.info("Lista %s (%s): %d registros (%d nuevos, %d cambiados [%d de estatus], %d sin cambio, %d retirados)",
             slug, mode, counts.entries, counts.added, counts.changed, counts.status_changed, counts.unchanged,
             counts.removed)
    return counts, upload_id


class WatchlistSync:
    def __init__(self, database: db.Database, bus: Bus, http: httpx.AsyncClient, settings: WatchlistSettings) -> None:
        self._db = database
        self._bus = bus
        self._http = http
        self._s = settings

    @property
    def sources(self) -> list[OfficialSource]:
        return [OFFICIAL_SOURCES[s] for s in self._s.sources if s in OFFICIAL_SOURCES and self.is_configured(s)]

    def is_configured(self, slug: str) -> bool:
        return slug != "worldbank" or bool(self._s.worldbank_api_key)

    async def run(self) -> None:
        while True:
            try:
                for source in self.sources:
                    if await self._due(source) and await self._bus.try_lock(f"watchlist:{source.slug}", 30 * 60):
                        try:
                            await self.refresh(source)
                        finally:
                            await self._bus.release(f"watchlist:{source.slug}")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Fallo al actualizar las listas negras")
            await asyncio.sleep(TICK_SECONDS)

    async def _due(self, source: OfficialSource) -> bool:
        async with self._db.session() as session:
            row = await session.get(db.WatchlistSource, source.slug)
        if row is None or row.last_checked_at is None:
            return True
        wait = self._s.retry_after if row.last_error else source.refresh_every
        return datetime.now(UTC) - row.last_checked_at >= wait

    async def download(self, source: OfficialSource) -> bytes:
        url = self._s.urls.get(source.slug, source.url)
        headers = {k: v.format(worldbank_api_key=self._s.worldbank_api_key) for k, v in source.headers}
        response = await self._http.get(url, headers=headers, follow_redirects=True,
                                        timeout=self._s.download_timeout.total_seconds())
        response.raise_for_status()
        return response.content

    async def refresh(self, source: OfficialSource) -> None:
        """Descarga y guarda una lista. Un error queda en la lista (panel de listas) y no tumba al worker."""
        now = datetime.now(UTC)
        try:
            data = await self.download(source)
            version = hashlib.sha256(data).hexdigest()
            async with self._db.session() as session:
                row = await self._row(session, source)
                if row.version == version and row.entry_count:
                    row.last_checked_at, row.last_error = now, None
                    await session.commit()
                    return
            records = await asyncio.to_thread(lambda: list(source.parser(data, source.slug)))
            if not records:
                raise ValueError("La lista llegó vacía; se conserva la versión anterior.")
            await save_list(self._db, source.slug, records, version, now, official=source)
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            message = redact_secrets(f"{type(ex).__name__}: {ex}")[:500]
            log.warning("No se pudo actualizar la lista %s: %s", source.slug, message)
            async with self._db.session() as session:
                row = await self._row(session, source)
                row.last_checked_at, row.last_error = now, message
                await session.commit()

    async def _row(self, session, source: OfficialSource) -> db.WatchlistSource:
        row = await session.get(db.WatchlistSource, source.slug)
        if row is None:
            row = db.WatchlistSource(slug=source.slug, name=source.name, category=source.category, custom=False,
                                     entry_count=0)
            session.add(row)
        return row
