"""Aplica las migraciones pendientes: python -m minos.migrate  (o "python -m minos.migrate revision -m 'mensaje'").

No necesita alembic.ini: las migraciones viajan dentro del paquete (minos/migrations).
"""
import logging
import sys

from alembic import command
from alembic.config import Config


def config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "minos:migrations")
    return cfg


def main(argv: list[str]) -> None:
    cfg = config()
    if not argv or argv[0] == "upgrade":
        command.upgrade(cfg, argv[1] if len(argv) > 1 else "head")
    elif argv[0] == "downgrade":
        command.downgrade(cfg, argv[1] if len(argv) > 1 else "-1")
    elif argv[0] == "revision":
        message = argv[argv.index("-m") + 1] if "-m" in argv else "cambio"
        command.revision(cfg, message=message, autogenerate=True)
    elif argv[0] == "current":
        command.current(cfg, verbose=True)
    else:
        sys.exit(f"Comando desconocido: {argv[0]} (usa upgrade, downgrade, revision o current)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    main(sys.argv[1:])
