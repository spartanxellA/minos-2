"""Cuentas desde la terminal del servidor, por ejemplo para crear el primer administrador:

    docker compose run --rm migrate python -m minos.users add admin@empresa.com --role admin --name "Xell"
    docker compose run --rm migrate python -m minos.users password admin@empresa.com
    docker compose run --rm migrate python -m minos.users list

La contraseña se pide en la terminal (o se toma de MINOS_NEW_PASSWORD si no hay terminal).
"""
import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select

from . import db
from .auth import Role, create_user, end_sessions, hash_password, normalize_email
from .config import get_settings


def _ask_password(minimum: int) -> str:
    password = os.environ.get("MINOS_NEW_PASSWORD")
    if not password:
        password = getpass.getpass("Contraseña: ")
        if getpass.getpass("Repite la contraseña: ") != password:
            sys.exit("Las contraseñas no coinciden.")
    if len(password) < minimum:
        sys.exit(f"La contraseña debe tener al menos {minimum} caracteres.")
    return password


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m minos.users", description="Cuentas de minOS")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="crea una cuenta")
    add.add_argument("email")
    add.add_argument("--name", default="")
    add.add_argument("--role", choices=[r.value for r in Role], default=Role.VIEWER.value)
    pw = sub.add_parser("password", help="cambia la contraseña, desbloquea y reactiva la cuenta")
    pw.add_argument("email")
    sub.add_parser("list", help="lista las cuentas")
    args = parser.parse_args(argv)

    settings = get_settings()
    database = db.Database(settings.database_url)
    try:
        async with database.session() as session:
            if args.command == "list":
                for u in (await session.scalars(select(db.User).order_by(db.User.email))).all():
                    print(f"{u.email}\t{u.role}\t{'activa' if u.active else 'desactivada'}\t{u.name}")
                return
            email = normalize_email(args.email)
            existing = await session.scalar(select(db.User).where(db.User.email == email))
            if args.command == "add":
                if existing is not None:
                    sys.exit(f"Ya existe una cuenta con {email}.")
                await create_user(session, email, args.name, Role(args.role), _ask_password(settings.auth.min_password_length))
                await session.commit()
                print(f"Cuenta creada: {email} ({args.role})")
            else:
                if existing is None:
                    sys.exit(f"No hay cuenta con {email}.")
                existing.password_hash = hash_password(_ask_password(settings.auth.min_password_length))
                existing.active = True
                existing.failed_logins = 0
                existing.locked_until = None
                await end_sessions(session, existing.id)
                await session.commit()
                print(f"Contraseña cambiada: {email}")
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
