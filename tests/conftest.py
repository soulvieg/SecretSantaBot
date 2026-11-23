import os

# db.engine builds its engine at import time, which calls get_settings().
# pytest must work without a real .env (and in CI), so provide dummies.
# This is a throwaway Fernet key: it only encrypts test payloads.
os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ENCRYPTION_KEY", "3rC932kWbzjA5q-RsawNA-_n_SbrOs1xufswdpAOEok=")

import itertools

import pytest
from sqlalchemy.orm import Session

from db.engine import build_engine
from db.models import Base, Circle, Participant, User


@pytest.fixture
def engine(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def make_user(session):
    counter = itertools.count(1)

    def _make(discord_id: str | None = None) -> User:
        user = User(discord_id=discord_id or str(next(counter)))
        session.add(user)
        session.flush()
        return user

    return _make


@pytest.fixture
def make_circle(session, make_user):
    def _make(owner: User | None = None, name: str = "Xmas") -> Circle:
        circle = Circle(name=name, owner_id=(owner or make_user()).id, discord_server_id=1, status="open")
        session.add(circle)
        session.flush()
        # server_default values (status, created_at) only exist in the database.
        session.refresh(circle)
        return circle

    return _make


@pytest.fixture
def make_participant(session, make_user):
    def _make(circle: Circle, user: User | None = None, *, ready: bool = False) -> Participant:
        participant = Participant(circle_id=circle.id, user_id=(user or make_user()).id, ready=ready)
        session.add(participant)
        session.flush()
        return participant

    return _make
