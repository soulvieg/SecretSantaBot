import random
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from crypto import decrypt_payload, encrypt_payload
from db.models import (
    Assignment,
    Circle,
    ContactInfo,
    Exclusion,
    Participant,
    Shipment,
    User,
    WishlistItem,
)
from draw import find_pairing


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

class OwnerCannotLeave(CircleError):
    pass

class DrawImpossible(CircleError):
    pass

class AlreadyClosed(CircleError):
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
    if user is None:
        raise RuntimeError(f"Could not read back user {discord_id}")
    return user


def create_circle(session: Session, *, name: str, owner_id:str, discord_server_id: int, budget: int | None = None, signup_deadline: datetime | None = None, exchange_date: datetime | None = None, avoid_repeat: bool = False) -> Circle:
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
    session.add(circle)
    try:
        session.flush()
    except IntegrityError as exc:
        raise GroupNameTaken(name) from exc
    join_circle(session, circle, owner_id)
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
    return session.scalar(query.order_by(Circle.created_at.desc()).limit(1))

def active_count(session: Session, circle_id: int) -> int:
    query = sa.select(sa.func.count()).select_from(Participant).where(Participant.circle_id == circle_id, Participant.withdrawn_at.is_(None))
    return session.scalar(query) or 0


def active_participants(session: Session, circle_id: int) -> list[Participant]:
    query = (
        sa.select(Participant)
        .where(Participant.circle_id == circle_id, Participant.withdrawn_at.is_(None))
        .order_by(Participant.id)
    )
    return list(session.scalars(query))

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
        if user.id == circle.owner_id:
            raise OwnerCannotLeave(circle.name)

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
    participant = session.scalar(sa.select(Participant).where(Participant.user_id == user.id, Participant.circle_id == circle.id))
    if participant is None or participant.withdrawn_at is not None:
        return "not signup to the event"
    return "participant"


def set_panel_message(session: Session, participant: Participant, msg_id: int) -> None:
    participant.panel_msg_id = msg_id
    session.flush()


def participant_from_panel(session: Session, msg_id: int) -> Participant | None:
    return session.scalar(sa.select(Participant).where(Participant.panel_msg_id == msg_id))


def set_ready(session: Session, participant: Participant, ready: bool = True) -> None:
    participant.ready = ready
    session.flush()


def all_ready(session: Session, circle_id: int) -> bool:
    active = sa.select(sa.func.count()).select_from(Participant).where(
        Participant.circle_id == circle_id, Participant.withdrawn_at.is_(None)
    )
    pending = active.where(Participant.ready.is_(False))
    return (session.scalar(active) or 0) >= 3 and (session.scalar(pending) or 0) == 0


def try_mark_drawn(session: Session, circle_id: int) -> bool:
    statement = (
        sa.update(Circle)
        .where(Circle.id == circle_id, Circle.status == "collecting")
        .values(status="drawn", current_round=Circle.current_round + 1)
        .returning(Circle.id)
    )
    return session.execute(statement).first() is not None


def save_contact(session: Session, participant: Participant, payload: dict) -> None:
    token = encrypt_payload(payload)
    row = session.scalar(sa.select(ContactInfo).where(ContactInfo.participant_id == participant.id))
    if row is None:
        session.add(ContactInfo(participant_id=participant.id, payload=token))
    else:
        row.payload = token
    session.flush()


def load_contact(session: Session, participant: Participant) -> dict | None:
    row = session.scalar(sa.select(ContactInfo).where(ContactInfo.participant_id == participant.id))
    if row is None:
        return None
    return decrypt_payload(row.payload)


def wishlist_count(session: Session, participant_id: int) -> int:
    query = sa.select(sa.func.count()).select_from(WishlistItem).where(WishlistItem.participant_id == participant_id)
    return session.scalar(query) or 0


def add_wishlist_item(session: Session, participant: Participant, *, title: str, url: str | None = None, price: int | None = None, note: str | None = None,) -> WishlistItem:
    item = WishlistItem(
        participant_id=participant.id,
        title=title,
        url=url,
        price=price,
        note=note,
        position=wishlist_count(session, participant.id),
    )
    session.add(item)
    session.flush()
    return item


def exclusion_ids(session: Session, participant: Participant) -> list[int]:
    query = (
        sa.select(Exclusion.excluded_participant_id)
        .where(Exclusion.giver_participant_id == participant.id)
        .order_by(Exclusion.id)
    )
    return list(session.scalars(query))


def wishlist_items(session: Session, participant: Participant) -> list[WishlistItem]:
    query = (
        sa.select(WishlistItem)
        .where(WishlistItem.participant_id == participant.id)
        .order_by(WishlistItem.position, WishlistItem.id)
    )
    return list(session.scalars(query))


def replace_exclusions(session: Session, circle: Circle, giver: Participant, excluded_ids: list[int]) -> None:
    session.execute(sa.delete(Exclusion).where(Exclusion.giver_participant_id == giver.id))
    allowed = set(
        session.scalars(
            sa.select(Participant.id).where(
                Participant.circle_id == circle.id,
                Participant.withdrawn_at.is_(None),
                Participant.id != giver.id,
            )
        )
    )
    seen: set[int] = set()
    for pid in excluded_ids:
        if pid not in allowed or pid in seen:
            continue
        seen.add(pid)
        session.add(
            Exclusion(
                circle_id=circle.id,
                giver_participant_id=giver.id,
                excluded_participant_id=pid,
            )
        )
    session.flush()


def draw_circle(
    session: Session, circle: Circle, rng: random.Random | None = None
) -> dict[int, int] | None:
    """Draw the current round. Returns giver -> receiver, or None if it was already drawn.

    Raises DrawImpossible when the constraints leave no valid pairing; in that
    case the circle is left untouched so people can relax their exclusions.
    """
    participants = active_participants(session, circle.id)
    exclusions = {
        participant.id: set(exclusion_ids(session, participant))
        for participant in participants
    }
    pairing = find_pairing(
        [participant.id for participant in participants],
        exclusions,
        rng or random.Random(),
    )
    if pairing is None:
        raise DrawImpossible(circle.name)

    round_no = circle.current_round + 1
    if not try_mark_drawn(session, circle.id):
        return None

    for giver_id, receiver_id in pairing.items():
        session.add(
            Assignment(
                circle_id=circle.id,
                round=round_no,
                giver_participant_id=giver_id,
                receiver_participant_id=receiver_id,
            )
        )
    session.flush()
    return pairing


def purge_personal_data(session: Session, circle_id: int) -> None:
    """Delete everything that identifies a person, keeping only ids and assignments."""
    participant_ids = sa.select(Participant.id).where(Participant.circle_id == circle_id)
    assignment_ids = sa.select(Assignment.id).where(Assignment.circle_id == circle_id)
    session.execute(sa.delete(Shipment).where(Shipment.assignment_id.in_(assignment_ids)))
    session.execute(sa.delete(ContactInfo).where(ContactInfo.participant_id.in_(participant_ids)))
    session.execute(sa.delete(WishlistItem).where(WishlistItem.participant_id.in_(participant_ids)))
    session.execute(sa.delete(Exclusion).where(Exclusion.circle_id == circle_id))
    session.flush()


def close_circle(session: Session, circle: Circle, discord_id: str) -> None:
    owner = session.scalar(sa.select(User).where(User.discord_id == discord_id))
    if owner is None or owner.id != circle.owner_id:
        raise NotOwner(circle.name)
    if circle.status == "closed":
        raise AlreadyClosed(circle.name)
    purge_personal_data(session, circle.id)
    circle.status = "closed"
    session.flush()


def due_open_circles(session: Session, now: datetime) -> list[int]:
    query = sa.select(Circle.id).where(
        Circle.status == "open",
        Circle.signup_deadline.is_not(None),
        Circle.signup_deadline <= now,
    )
    return list(session.scalars(query))


def stale_drawn_circles(session: Session, cutoff: datetime) -> list[int]:
    query = sa.select(Circle.id).where(
        Circle.status == "drawn",
        Circle.exchange_date.is_not(None),
        Circle.exchange_date <= cutoff,
    )
    return list(session.scalars(query))


def leave_any_time(session: Session, circle: Circle, discord_id: str) -> tuple[str, int | None]:
    """Withdraw a participant, re-linking the chain when names are already drawn.

    Returns "left" (nothing else to do), "spliced" or "reset" (the round was
    cancelled and the circle is collecting again).
    """
    if circle.status == "closed":
        raise GroupNotOpen(circle.name)
    user = session.scalar(sa.select(User).where(User.discord_id == discord_id))
    if user is not None and user.id == circle.owner_id:
        raise OwnerCannotLeave(circle.name)
    participant = None
    if user is not None:
        participant = session.scalar(
            sa.select(Participant).where(
                Participant.circle_id == circle.id, Participant.user_id == user.id
            )
        )
    if participant is None or participant.withdrawn_at is not None:
        raise NotJoined(circle.name)

    participant.withdrawn_at = utc_to_now()
    session.flush()
    if circle.status != "drawn":
        return "left", None

    round_no = circle.current_round
    outgoing = session.scalar(
        sa.select(Assignment).where(
            Assignment.circle_id == circle.id,
            Assignment.round == round_no,
            Assignment.giver_participant_id == participant.id,
        )
    )
    incoming = session.scalar(
        sa.select(Assignment).where(
            Assignment.circle_id == circle.id,
            Assignment.round == round_no,
            Assignment.receiver_participant_id == participant.id,
        )
    )
    if outgoing is None or incoming is None:
        return "left", None

    donor = incoming.giver_participant_id
    beneficiary = outgoing.receiver_participant_id
    session.delete(outgoing)
    session.delete(incoming)
    session.flush()

    two_cycle = donor == beneficiary or session.scalar(
        sa.select(Assignment.id).where(
            Assignment.circle_id == circle.id,
            Assignment.round == round_no,
            Assignment.giver_participant_id == beneficiary,
            Assignment.receiver_participant_id == donor,
        )
    )
    if two_cycle or active_count(session, circle.id) < 3:
        session.execute(
            sa.delete(Assignment).where(
                Assignment.circle_id == circle.id, Assignment.round == round_no
            )
        )
        circle.current_round = max(circle.current_round - 1, 0)
        circle.status = "collecting"
        for remaining in active_participants(session, circle.id):
            remaining.ready = False
        session.flush()
        return "reset", None

    session.add(
        Assignment(
            circle_id=circle.id,
            round=round_no,
            giver_participant_id=donor,
            receiver_participant_id=beneficiary,
        )
    )
    session.flush()
    return "spliced", donor


def add_participant_after_draw(
    session: Session, circle: Circle, discord_id: str
) -> tuple[int, int]:
    """Insert a participant into the drawn chain. Returns (participant_id, new_giver_id)."""
    if circle.status != "drawn":
        raise GroupNotOpen(circle.name)
    user = get_user(session, discord_id)
    participant = session.scalar(
        sa.select(Participant).where(
            Participant.circle_id == circle.id, Participant.user_id == user.id
        )
    )
    if participant is not None and participant.withdrawn_at is None:
        raise AlreadyJoined(circle.name)

    round_no = circle.current_round
    edge = session.scalar(
        sa.select(Assignment)
        .where(Assignment.circle_id == circle.id, Assignment.round == round_no)
        .order_by(Assignment.id.desc())
        .limit(1)
    )
    if edge is None:
        raise GroupNotFound(circle.name)

    giver_id = edge.giver_participant_id
    receiver_id = edge.receiver_participant_id
    session.delete(edge)
    session.flush()

    if participant is None:
        participant = Participant(circle_id=circle.id, user_id=user.id)
        session.add(participant)
        session.flush()
    else:
        participant.withdrawn_at = None
        participant.ready = False
        session.flush()

    session.add(
        Assignment(
            circle_id=circle.id,
            round=round_no,
            giver_participant_id=giver_id,
            receiver_participant_id=participant.id,
        )
    )
    session.add(
        Assignment(
            circle_id=circle.id,
            round=round_no,
            giver_participant_id=participant.id,
            receiver_participant_id=receiver_id,
        )
    )
    session.flush()
    return participant.id, giver_id


def assignment_for(session: Session, circle_id: int, giver_participant_id: int) -> Assignment | None:
    circle = session.get(Circle, circle_id)
    if circle is None:
        return None
    return session.scalar(
        sa.select(Assignment).where(
            Assignment.circle_id == circle_id,
            Assignment.round == circle.current_round,
            Assignment.giver_participant_id == giver_participant_id,
        )
    )
