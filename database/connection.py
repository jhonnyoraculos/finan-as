"""PostgreSQL/Neon connection and transaction lifecycle helpers."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

try:  # Streamlit is optional for database-only scripts and unit tests.
    import streamlit as st
    from streamlit.errors import StreamlitSecretNotFoundError
except ImportError:  # pragma: no cover - exercised only in minimal environments
    st = None  # type: ignore[assignment]


def _read_streamlit_secret(key: str) -> str | None:
    if st is None:
        return None
    try:
        value = st.secrets.get(key)
    except StreamlitSecretNotFoundError:
        # Streamlit raises when no secrets file exists. The environment fallback is
        # expected for CLI scripts and hosted environments.
        return None
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def get_database_url(explicit_url: str | None = None) -> str:
    """Resolve a database URL without ever embedding credentials in source.

    Resolution order is: explicit argument (useful in tests),
    ``st.secrets["DATABASE_URL"]``, then the ``DATABASE_URL`` environment variable.
    """

    value = (
        explicit_url.strip()
        if explicit_url and explicit_url.strip()
        else _read_streamlit_secret("DATABASE_URL")
        or os.getenv("DATABASE_URL", "").strip()
    )
    if not value:
        raise RuntimeError(
            "DATABASE_URL não configurada. Defina-a em .streamlit/secrets.toml "
            "ou como variável de ambiente."
        )
    return value


def normalize_database_url(database_url: str) -> str:
    """Select psycopg 3 for ordinary PostgreSQL/Neon URLs.

    URLs with an explicit SQLAlchemy driver (and non-PostgreSQL URLs injected by
    tests) remain untouched.
    """

    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url[len("postgres://") :]
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url[len("postgresql://") :]
    return database_url


def create_db_engine(database_url: str | None = None, **overrides: Any) -> Engine:
    """Create an SQLAlchemy 2.x engine suitable for Neon connection pooling."""

    resolved_url = normalize_database_url(get_database_url(database_url))
    parsed_url = make_url(resolved_url)
    backend = parsed_url.get_backend_name()
    options: dict[str, Any] = {
        "pool_pre_ping": True,
        "future": True,
    }
    if backend == "postgresql":
        options.update(
            pool_recycle=300,
            pool_size=5,
            max_overflow=5,
            pool_timeout=30,
        )
    elif backend == "sqlite":  # Test injection only; PostgreSQL remains the app database.
        options["connect_args"] = {"check_same_thread": False}
        if parsed_url.database in {None, "", ":memory:"} or parsed_url.query.get("mode") == "memory":
            options["poolclass"] = StaticPool
    options.update(overrides)
    return create_engine(resolved_url, **options)


if st is not None:
    _engine_cache = st.cache_resource(show_spinner=False)(create_db_engine)
else:  # pragma: no cover - Streamlit is an application dependency
    from functools import lru_cache

    _engine_cache = lru_cache(maxsize=8)(create_db_engine)


def get_engine(database_url: str | None = None) -> Engine:
    """Return one cached engine/pool per resolved URL in the current process."""

    # Resolve before caching so an environment-backed call and an explicit call for
    # the same database share one pool.
    return _engine_cache(get_database_url(database_url))


def dispose_engine(database_url: str | None = None) -> None:
    """Dispose cached pools, primarily for test teardown and credential rotation."""

    try:
        get_engine(database_url).dispose()
    finally:
        clear = getattr(_engine_cache, "clear", None)
        if clear:
            clear()


def get_session_factory(
    database_url: str | None = None, *, engine: Engine | None = None
) -> sessionmaker[Session]:
    """Build a session factory; an engine can be injected by tests."""

    bind = engine or get_engine(database_url)
    return sessionmaker(
        bind=bind,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


@contextmanager
def session_scope(
    database_url: str | None = None, *, engine: Engine | None = None
) -> Iterator[Session]:
    """Provide an atomic transaction with automatic commit/rollback/close."""

    session = get_session_factory(database_url, engine=engine)()
    try:
        with session.begin():
            yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database_connection(
    database_url: str | None = None, *, engine: Engine | None = None
) -> bool:
    """Perform a lightweight, parameter-free health check."""

    bind = engine or get_engine(database_url)
    with bind.connect() as connection:
        connection.execute(text("SELECT 1"))
    return True


def safe_database_url(database_url: str | URL | None = None) -> str:
    """Return a password-masked URL suitable for logs."""

    url = (
        database_url
        if isinstance(database_url, URL)
        else make_url(get_database_url(database_url))
    )
    return url.render_as_string(hide_password=True)


__all__ = [
    "check_database_connection",
    "create_db_engine",
    "dispose_engine",
    "get_database_url",
    "get_engine",
    "get_session_factory",
    "normalize_database_url",
    "safe_database_url",
    "session_scope",
]
