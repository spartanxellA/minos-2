"""Ubica menciones guardadas antes del mapa (o todas de nuevo con --all) con lo que quedó en la base.

De las menciones viejas no se guardó la ubicación del perfil, así que solo se aprovechan el medio (RSS), la
comunidad (Reddit) y el texto. Uso: python -m minos.geo.backfill [--all] [--target <id>]
"""
import argparse
import asyncio
import uuid

from sqlalchemy import select

from .. import db
from ..config import GeoSettings, get_settings
from ..domain.mentions import GeoHint
from .locate import locate


def _hint(m: db.Mention) -> GeoHint | None:
    if m.source == "rss":
        return GeoHint(outlet_name=m.author_handle)
    if m.source == "reddit" and m.author_name:
        return GeoHint(community=m.author_name.removeprefix("r/"))
    return None


async def locate_stored(session, target: db.Target, settings: GeoSettings, *, redo: bool = False, batch: int = 500) -> int:
    """Ubica las menciones pendientes de un objetivo por tandas; devuelve cuántas revisó."""
    names = target.to_domain().search_names()
    done = 0
    last_id: uuid.UUID | None = None
    while True:
        query = select(db.Mention).where(db.Mention.target_id == target.id).order_by(db.Mention.id).limit(batch)
        if not redo:
            query = query.where(db.Mention.geo_method.is_(None))
        if last_id is not None:
            query = query.where(db.Mention.id > last_id)
        rows = (await session.scalars(query)).all()
        if not rows:
            return done
        for m in rows:
            m.set_location(locate(_hint(m), m.text, names, settings))
        await session.commit()
        session.expunge_all()
        done += len(rows)
        last_id = rows[-1].id


async def main(redo: bool, target_id: uuid.UUID | None) -> None:
    settings = get_settings()
    database = db.Database(settings.database_url)
    try:
        async with database.session() as session:
            query = select(db.Target)
            if target_id:
                query = query.where(db.Target.id == target_id)
            for target in (await session.scalars(query)).all():
                count = await locate_stored(session, target, settings.ingestion.geo, redo=redo)
                print(f"{target.name}: {count} menciones revisadas")
    finally:
        await database.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="vuelve a ubicar también las que ya tienen ubicación")
    parser.add_argument("--target", type=uuid.UUID, help="solo este objetivo")
    args = parser.parse_args()
    asyncio.run(main(args.all, args.target))
