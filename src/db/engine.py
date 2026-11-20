from collections.abc import Iterator
from contextlib import contextmanager

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import cursor
from sqlalchemy.orm import Session, sessionmaker

from config import get_settings


def _enable_sqlite(conn, _record) -> None:
    curs = conn.cursor()
    curs.execute("PRAGMA foreign_keys=ON")
    curs.execute("PRAGMA journal_mode=WAL")
    curs.close()

def build_engine(url: str) -> sa.Engine:
    engine = sa.create_engine(url)
    event.listen(engine, "connect", _enable_sqlite)
    return engine

engine = build_engine(get_settings().db_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

@contextmanager
def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
