"""Mapa: dónde se genera la información sobre un objetivo, por país, estado de México y ciudad."""
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit, db
from ..auth import CurrentUser, Role, current_user, require_role
from ..domain.mentions import Sentiment
from ..schemas import Camel
from .backfill import locate_stored
from .gazetteer import COUNTRY_NAMES, REGION_NAMES, place_label

# "origin": de dónde es quien publica (geoetiqueta, perfil, comunidad, medio). "text": de qué lugar habla la nota.
Basis = Literal["all", "origin", "text"]


class AreaCount(Camel):
    code: str
    name: str
    count: int
    negative: int


class PlaceCount(Camel):
    name: str
    country: str
    region: str | None
    lat: float
    lon: float
    precision: str
    count: int
    negative: int


class MethodCount(Camel):
    method: str
    count: int


class SourceCoverage(Camel):
    source: str
    total: int
    located: int


class GeoOverview(Camel):
    since: datetime
    until: datetime
    basis: Basis
    # Todas las menciones del periodo (con el filtro de fuente) y cuántas tienen ubicación con la base elegida.
    total: int
    located: int
    by_method: list[MethodCount]
    by_source: list[SourceCoverage]
    countries: list[AreaCount]
    # Solo estados de México.
    regions: list[AreaCount]
    # Ciudades, estados o países como puntos, del más mencionado al menos.
    places: list[PlaceCount]
    # Menciones del objetivo (de cualquier fecha) que se guardaron antes del mapa y aún no se han intentado ubicar.
    pending: int


async def get_session(request: Request):
    async with request.app.state.db.session() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]
geo_router = APIRouter(prefix="/api/targets/{target_id}/geo", dependencies=[Depends(current_user)])


async def _target(session: AsyncSession, target_id: uuid.UUID) -> db.Target:
    target = await session.get(db.Target, target_id)
    if target is None:
        raise HTTPException(404, "Objetivo no encontrado")
    return target


@geo_router.get("", response_model=GeoOverview)
async def geo_overview(
    target_id: uuid.UUID,
    session: Session,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    source: str | None = None,
    basis: Basis = "all",
):
    await _target(session, target_id)
    M = db.Mention
    until = datetime.now(UTC)
    since = until - timedelta(days=days)
    negative = func.sum(func.cast(M.sentiment == Sentiment.NEGATIVE.value, Integer))
    query = (
        select(M.source, M.geo_country, M.geo_region, M.geo_city, M.geo_precision, M.geo_method,
               func.min(M.geo_lat), func.min(M.geo_lon), func.count(), negative)
        .where(M.target_id == target_id, M.published_at >= since)
        .group_by(M.source, M.geo_country, M.geo_region, M.geo_city, M.geo_precision, M.geo_method)
    )
    if source:
        query = query.where(M.source == source)
    rows = (await session.execute(query)).all()

    total = located = 0
    by_method: dict[str, int] = defaultdict(int)
    by_source: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    countries: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    regions: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    places: dict[str, dict] = {}
    for src, country, region, city, precision, method, lat, lon, count, neg in rows:
        neg = int(neg or 0)
        total += count
        by_source[src][0] += count
        if country is None or (basis != "all" and (basis == "text") != (method == "text")):
            continue
        located += count
        by_source[src][1] += count
        by_method[method] += count
        countries[country][0] += count
        countries[country][1] += neg
        if region:
            regions[region][0] += count
            regions[region][1] += neg
        name = place_label(country, region, city)
        p = places.setdefault(name, {
            "name": name, "country": country, "region": region, "lat": lat, "lon": lon,
            # Una geoetiqueta exacta se dibuja en su ciudad (o estado) para agrupar.
            "precision": "city" if precision == "point" and city else precision, "count": 0, "negative": 0,
        })
        p["count"] += count
        p["negative"] += neg

    def areas(data: dict[str, list[int]], names: dict[str, str]) -> list[AreaCount]:
        return sorted((AreaCount(code=k, name=names.get(k, k), count=v[0], negative=v[1]) for k, v in data.items()),
                      key=lambda a: -a.count)

    pending = await session.scalar(
        select(func.count()).select_from(M).where(M.target_id == target_id, M.geo_method.is_(None))
    )
    return GeoOverview(
        since=since, until=until, basis=basis, total=total, located=located,
        by_method=sorted((MethodCount(method=k, count=v) for k, v in by_method.items()), key=lambda m: -m.count),
        by_source=sorted((SourceCoverage(source=k, total=v[0], located=v[1]) for k, v in by_source.items()),
                         key=lambda s: -s.total),
        countries=areas(countries, COUNTRY_NAMES),
        regions=areas(regions, REGION_NAMES),
        places=[PlaceCount(**p) for p in sorted(places.values(), key=lambda p: -p["count"])],
        pending=pending or 0,
    )


class LocateResult(Camel):
    reviewed: int


@geo_router.post("/locate", response_model=LocateResult, dependencies=[Depends(require_role(Role.ANALYST))])
async def locate_pending(
    target_id: uuid.UUID, session: Session, request: Request, me: Annotated[CurrentUser, Depends(current_user)],
):
    """Ubica las menciones del objetivo guardadas antes del mapa, con el medio, la comunidad y el texto."""
    target = await _target(session, target_id)
    name = target.name
    reviewed = await locate_stored(session, target, request.app.state.settings.ingestion.geo)
    audit.record(session, request, "mentions.geolocated", me, entity_type="target", entity_id=target_id,
                 entity_label=name, detail={"reviewed": reviewed})
    await session.commit()
    return LocateResult(reviewed=reviewed)
