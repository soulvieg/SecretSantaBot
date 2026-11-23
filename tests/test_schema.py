import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import (
    Assignment,
    Circle,
    Exclusion,
    Participant,
    Shipment,
    User,
)


def make_user(session: Session, discord_id: str) -> User:
    user = User(discord_id=discord_id)
    session.add(user)
    session.commit()
    return user


def make_circle(session: Session, owner: User, name: str = "Xmas") -> Circle:
    circle = Circle(name=name, owner_id=owner.id, discord_server_id=1)
    session.add(circle)
    session.commit()
    return circle


def make_participant(session: Session, circle: Circle, user: User) -> Participant:
    participant = Participant(circle_id=circle.id, user_id=user.id)
    session.add(participant)
    session.commit()
    return participant


def make_assignment(session: Session, circle: Circle, giver: Participant, receiver: Participant) -> Assignment:
    assignment = Assignment(
        circle_id=circle.id,
        round=1,
        giver_participant_id=giver.id,
        receiver_participant_id=receiver.id,
    )
    session.add(assignment)
    session.commit()
    return assignment


def test_foreign_keys_pragma_is_on(engine):
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_user_needs_a_platform_id(session):
    session.add(User())
    with pytest.raises(IntegrityError):
        session.commit()


def test_user_can_be_identified_only_by_discord(session):
    user = make_user(session, "123")
    assert user.id is not None


def test_same_user_twice_in_one_circle_is_rejected(session):
    owner = make_user(session, "1")
    circle = make_circle(session, owner)
    make_participant(session, circle, owner)
    session.add(Participant(circle_id=circle.id, user_id=owner.id))
    with pytest.raises(IntegrityError):
        session.commit()


def test_same_user_in_two_circles_is_allowed(session):
    owner = make_user(session, "1")
    first = make_circle(session, owner, "Xmas")
    second = make_circle(session, owner, "Birthday")
    make_participant(session, first, owner)
    make_participant(session, second, owner)
    assert first.id != second.id


def test_participant_blocks_user_deletion(session):
    owner = make_user(session, "1")
    member = make_user(session, "2")
    circle = make_circle(session, owner)
    make_participant(session, circle, member)
    session.delete(member)
    with pytest.raises(IntegrityError):
        session.commit()


def test_assignment_rejects_self_gift(session):
    owner = make_user(session, "1")
    circle = make_circle(session, owner)
    participant = make_participant(session, circle, owner)
    session.add(
        Assignment(
            circle_id=circle.id,
            round=1,
            giver_participant_id=participant.id,
            receiver_participant_id=participant.id,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_receiver_cannot_have_two_santas_in_same_round(session):
    owner = make_user(session, "1")
    a = make_user(session, "2")
    b = make_user(session, "3")
    c = make_user(session, "4")
    circle = make_circle(session, owner)
    pa = make_participant(session, circle, a)
    pb = make_participant(session, circle, b)
    pc = make_participant(session, circle, c)
    make_assignment(session, circle, pa, pb)
    session.add(
        Assignment(
            circle_id=circle.id,
            round=1,
            giver_participant_id=pc.id,
            receiver_participant_id=pb.id,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_same_pair_can_repeat_in_a_later_round(session):
    owner = make_user(session, "1")
    other = make_user(session, "2")
    circle = make_circle(session, owner)
    pa = make_participant(session, circle, owner)
    pb = make_participant(session, circle, other)
    make_assignment(session, circle, pa, pb)
    session.add(
        Assignment(
            circle_id=circle.id,
            round=2,
            giver_participant_id=pa.id,
            receiver_participant_id=pb.id,
        )
    )
    session.commit()


def test_one_shipment_per_assignment(session):
    owner = make_user(session, "1")
    other = make_user(session, "2")
    circle = make_circle(session, owner)
    pa = make_participant(session, circle, owner)
    pb = make_participant(session, circle, other)
    assignment = make_assignment(session, circle, pa, pb)
    session.add(Shipment(assignment_id=assignment.id, carrier="Poste Italiane"))
    session.commit()
    session.add(Shipment(assignment_id=assignment.id, carrier="DHL"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_exclusion_rejects_excluding_himself(session):
    owner = make_user(session, "1")
    circle = make_circle(session, owner)
    participant = make_participant(session, circle, owner)
    session.add(
        Exclusion(
            circle_id=circle.id,
            giver_participant_id=participant.id,
            excluded_participant_id=participant.id,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
