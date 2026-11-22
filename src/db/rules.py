from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import Circle, Participant, User

class CircleError(Exception):
    """Errors messages to show from UI to user"""

class GroupNotFound(CircleError):
    pass

class GroupNameTaken(CircleError):
    pass

class GroupNotOpen(CircleError):
    pass

class AlreadyJoined(CircleError):
    pass

class NotJoined(CircleError):
    pass

class NotOwner(CircleError):
    pass

def utc_to_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

def get_user(session: Session, discord_id: str) -> User:
    user = session.scalar(sa.select(User).where(User.discord_id == discord_id))
    if user is not None:
        return user
    try:
        with session.begin_nested():
            user = User(discord_id=discord_id)
            session.add(user)
    except IntegrityError:
        user = session.scalar(sa.select(User).where(User.discord_id == discord_id))
    return user


def create_circle(session: Session, *, name: str, owner_id:str, discord_server_id:str, budget: int | None = None, signup_deadline: datetime | None = None, exchange_date: datetime | None = None, avoid_repeat: bool = False) -> Circle:
    owner = get_user(session, owner_id)
    circle = Circle(
        name = name,
        owner_id = owner.id,
        discord_server_id = discord_server_id,
        status = "open",
        budget = budget,
        signup_deadline = signup_deadline,
        exchange_date = exchange_date,
        avoid_repeat = avoid_repeat
    )
    try:
        session.flush()
    except IntegrityError as exc:
        raise GroupNameTaken(name) from exc
    return circle


def set_card(session: Session, circle_id: int, channel_id: int, msg_id: int) -> None:
    circle = session.get(Circle, circle_id)
    if circle is None:
        raise GroupNotFound(circle_id)
    circle.announce_channel_id = channel_id
    circle.card_msg_id = msg_id


def circle_from_card(session: Session, msg_id: int) -> Circle | None:
    return session.scalar(sa.select(Circle).where(Circle.card_msg_id == msg_id))


def find_circle(session: Session, server_id: int , name: str | None = None, channel_id: int | None = None) -> Circle | None:
    query = sa.select(Circle).where(Circle.discord_server_id == server_id, Circle.status != "closed")
    if name:
        query = query.where(Circle.name == name)
    elif channel_id:
        query = query.where(Circle.announce_channel_id == channel_id)
    return session.scalar(query.order_by(Circle.created_at.desc().limit(1)))

def active_count(session: Session, circle_id: int) -> int:
    query = sa.select(sa.func.count()).select_from(Participant).where(Participant.circle_id == circle_id, Participant.withdrawn_at.is_(None))
    return session.scalar(query) or 0

def join_circle(session: Session, circle: Circle, discord_id: str) -> Participant:
    if circle.status != "open":
        raise GroupNotOpen(circle.name)
    user = get_user(session, discord_id)
    participant = session.scalar(sa.select(Participant).where(Participant.circle_id  == circle.id, Participant.user_id == user.id))
    if participant is not None:
        if participant.withdrawn_at is None:
            raise AlreadyJoined(circle.name)
        participant.withdrawn_at = None
        session.flush()
        return participant
    participant = Participant(circle_id = circle.id, user_id = user.id)
    session.add(participant)
    session.flush()
    return participant


def leave_circle(session: Session, circle: Circle, discord_id: str) -> None:
    if circle.status != "open":
        raise GroupNotOpen(circle.name)
    user = session.scalar(sa.select(User).where(User.discord_id == discord_id))
    participant = None
    if user is not None:
        participant = session.scalar(sa.select(Participant).where(Participant.circle_id == circle.id, Participant.user_id == user.id))
    if participant is None or participant.withdrawn_at is not None:
        raise NotJoined(circle.name)
    participant.withdrawn_at = utc_to_now()
    session.flush()



def close_signup(session: Session, circle: Circle, discord_id: str) -> None:
    owner = session.scalar(sa.select(User).where(User.discord_id == discord_id))
    if owner is None or owner.id != circle.owner_id:
        raise NotOwner(circle.name)
    if circle.status != "open":
        raise GroupNotOpen(circle.name)
    circle.status = "collecting"

def owner_discord_id(session: Session, circle: Circle) -> str:
    owner = session.get(User, circle.owner_id)
    return owner.discord_id if owner and owner.discord_id else ""

def role_of(session: Session, circle: Circle, discord_id: str) -> str:
    user = session.scalar(sa.select(User).where(User.discord_id == discord_id))
    if user is None:
        return "not signup to the event"
    if user.id == circle.owner_id:
        return "organizer"
    participant = session.scalar(sa.select(Participant).where(Participant.user_id == user.id))
    if participant is None or participant.withdrawn_at is not None:
        return "not signup to the event"
    return "participant"
