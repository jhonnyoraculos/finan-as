"""Non-destructive database initialization command.

Run with ``python -m database.init_db`` after configuring ``DATABASE_URL``.
This module only creates missing tables and indexes; it never drops or seeds data.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

from sqlalchemy import Engine, inspect

from .connection import check_database_connection, get_engine, safe_database_url
from .models import Base

logger = logging.getLogger(__name__)


def init_database(
    database_url: str | None = None, *, engine: Engine | None = None
) -> list[str]:
    """Create all missing tables and return the tables visible afterwards.

    ``MetaData.create_all`` is intentionally idempotent and non-destructive.
    Schema changes to existing columns should later be managed with migrations.
    """

    bind = engine or get_engine(database_url)
    Base.metadata.create_all(bind=bind, checkfirst=True)
    return sorted(inspect(bind).get_table_names())


def database_has_users(
    database_url: str | None = None, *, engine: Engine | None = None
) -> bool:
    """Return whether onboarding has already created at least one user."""

    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from .models import User

    bind = engine or get_engine(database_url)
    with Session(bind) as session:
        return bool(
            session.scalar(select(func.count(User.id)).where(User.deleted_at.is_(None)))
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cria, sem apagar dados, as tabelas do Finanças Pessoais."
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Apenas testa a conexão; não executa CREATE TABLE.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = _build_parser().parse_args(argv)
    try:
        check_database_connection()
        logger.info("Conexão estabelecida com %s", safe_database_url())
        if args.check_only:
            return 0
        tables = init_database()
        logger.info("Banco inicializado; %d tabelas disponíveis.", len(tables))
        return 0
    except Exception:
        # Details go to the terminal log; UI code can show a concise message.
        logger.exception("Não foi possível inicializar o banco.")
        return 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())


__all__ = ["database_has_users", "init_database", "main"]
