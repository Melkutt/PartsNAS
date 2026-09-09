"""SQLAlchemy engine / session wiring for SQLite.

SQLite is a deliberate choice: one file, trivial backup (copy it), and plenty for
a single-user bench database on a DS224+. `check_same_thread=False` + a short busy
timeout is enough for FastAPI's threadpool; WAL keeps reads non-blocking.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Boolean, DateTime, Float, Integer, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False, "timeout": 15},
    future=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _sqlite_type(col) -> str:
    t = col.type
    if isinstance(t, Boolean):
        return "INTEGER"
    if isinstance(t, Integer):
        return "INTEGER"
    if isinstance(t, Float):
        return "REAL"
    if isinstance(t, DateTime):
        return "TEXT"
    return "TEXT"  # String / Text / JSON


def _default_sql(col) -> str:
    d = getattr(col, "default", None)
    if d is None or not getattr(d, "is_scalar", False):
        return ""
    v = d.arg
    if isinstance(v, bool):
        return f" DEFAULT {1 if v else 0}"
    if isinstance(v, (int, float)):
        return f" DEFAULT {v}"
    if isinstance(v, str):
        return " DEFAULT '{}'".format(v.replace("'", "''"))
    return ""


def sync_columns() -> list[str]:
    """Lightweight additive migration: ADD COLUMN for any mapped column the table
    is missing. Covers this project's only kind of schema change (new nullable /
    scalar-default columns) so the user's data survives an app update without
    Alembic. New columns are added nullable; the app fills non-null defaults."""
    added: list[str] = []
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = f'"{col.name}" {_sqlite_type(col)}{_default_sql(col)}'
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}'))
                added.append(f"{table.name}.{col.name}")
    return added
