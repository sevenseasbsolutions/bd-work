"""One engine, one session maker, one Base. Nothing else lives here.

SQLite by default so the whole thing runs from a clone with no service to
start; point MBS_DATABASE_URL at Postgres and the same models apply.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DB_URL = os.environ.get("MBS_DATABASE_URL", "")
if not DB_URL:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_URL = "sqlite:///" + os.path.join(here, "mbs.db")

# check_same_thread is a SQLite-only argument; passing it to Postgres raises.
_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, connect_args=_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency. One session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
