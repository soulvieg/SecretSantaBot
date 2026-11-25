import random

import pytest
import sqlalchemy as sa

from db import rules
from db.models import Assignment


def drawn_circle(session, count: int):
    """A drawn circle with `count` participants, owner "100" included."""
    circle = rules.create_circle(session, name="Xmas", owner_id="100", discord_server_id=1)
    for discord_id in range(2, count + 1):
        rules.join_circle(session, circle, str(discord_id))
    for participant in rules.active_participants(session, circle.id):
        rules.set_ready(session, participant)
    rules.close_signup(session, circle, "100")
    session.flush()
    session.refresh(circle)
    rules.draw_circle(session, circle, random.Random(1))
    session.flush()
    session.refresh(circle)
    return circle


def edges(session, circle_id: int, round_no: int) -> dict[int, int]:
    rows = session.scalars(
        sa.select(Assignment).where(
            Assignment.circle_id == circle_id, Assignment.round == round_no
        )
    )
    return {row.giver_participant_id: row.receiver_participant_id for row in rows}


def participant_id(session, circle_id: int, discord_id: str) -> int:
    user = rules.get_user(session, discord_id)
    found = session.scalar(
        sa.select(rules.Participant).where(
            rules.Participant.circle_id == circle_id,
            rules.Participant.user_id == user.id,
        )
    )
    assert found is not None
    return found.id


def test_leave_while_collecting_just_withdraws(session):
    circle = rules.create_circle(session, name="Xmas", owner_id="100", discord_server_id=1)
    for discord_id in (2, 3, 4):
        rules.join_circle(session, circle, str(discord_id))
    rules.close_signup(session, circle, "100")

    state, donor = rules.leave_any_time(session, circle, "3")

    assert state == "left"
    assert donor is None
    assert rules.active_count(session, circle.id) == 3
    assert circle.status == "collecting"


def test_leave_after_draw_splices_the_chain(session):
    circle = drawn_circle(session, 4)
    before = edges(session, circle.id, 1)
    leaver = participant_id(session, circle.id, "3")
    donor = next(giver for giver, receiver in before.items() if receiver == leaver)
    beneficiary = before[leaver]

    state, notified = rules.leave_any_time(session, circle, "3")

    assert state == "spliced"
    assert notified == donor
    after = edges(session, circle.id, 1)
    assert leaver not in after
    assert leaver not in after.values()
    assert after[donor] == beneficiary
    assert len(after) == 3
    assert sorted(after.values()) == sorted(after)


def test_leave_after_draw_with_three_people_cancels_the_round(session):
    circle = drawn_circle(session, 3)

    state, donor = rules.leave_any_time(session, circle, "3")

    session.refresh(circle)
    assert state == "reset"
    assert donor is None
    assert circle.status == "collecting"
    assert circle.current_round == 0
    assert edges(session, circle.id, 1) == {}
    assert all(not p.ready for p in rules.active_participants(session, circle.id))


def test_leave_after_draw_cancels_when_splice_would_make_a_two_cycle(session):
    circle = drawn_circle(session, 6)
    ids = [p.id for p in rules.active_participants(session, circle.id)]
    session.execute(sa.delete(Assignment).where(Assignment.circle_id == circle.id))
    session.flush()
    for giver, receiver in [
        (ids[0], ids[1]),
        (ids[1], ids[2]),
        (ids[2], ids[0]),
        (ids[3], ids[4]),
        (ids[4], ids[5]),
        (ids[5], ids[3]),
    ]:
        session.add(
            Assignment(
                circle_id=circle.id,
                round=1,
                giver_participant_id=giver,
                receiver_participant_id=receiver,
            )
        )
    session.flush()

    state, _ = rules.leave_any_time(session, circle, "3")

    session.refresh(circle)
    assert state == "reset"
    assert circle.status == "collecting"
    assert edges(session, circle.id, 1) == {}


def test_owner_cannot_leave_after_draw(session):
    circle = drawn_circle(session, 4)

    with pytest.raises(rules.OwnerCannotLeave):
        rules.leave_any_time(session, circle, "100")


def test_cannot_leave_a_closed_circle(session):
    circle = drawn_circle(session, 4)
    circle.status = "closed"
    session.flush()

    with pytest.raises(rules.GroupNotOpen):
        rules.leave_any_time(session, circle, "3")


def test_add_after_draw_splices_the_new_participant(session):
    circle = drawn_circle(session, 4)
    before = edges(session, circle.id, 1)

    new_id, donor = rules.add_participant_after_draw(session, circle, "99")

    after = edges(session, circle.id, 1)
    assert len(after) == 5
    assert sorted(after.values()) == sorted(after)
    old_receiver = before[donor]
    assert after[donor] == new_id
    assert after[new_id] == old_receiver
    assert rules.active_count(session, circle.id) == 5
    assert circle.status == "drawn"
    assert circle.current_round == 1


def test_add_reuses_a_withdrawn_participant(session):
    circle = drawn_circle(session, 4)
    rules.leave_any_time(session, circle, "3")
    withdrawn_id = participant_id(session, circle.id, "3")

    new_id, _ = rules.add_participant_after_draw(session, circle, "3")

    assert new_id == withdrawn_id
    participant = session.get(rules.Participant, new_id)
    assert participant is not None
    assert participant.withdrawn_at is None


def test_add_requires_a_drawn_circle(session):
    circle = rules.create_circle(session, name="Xmas", owner_id="100", discord_server_id=1)
    rules.join_circle(session, circle, "2")
    rules.close_signup(session, circle, "100")

    with pytest.raises(rules.GroupNotOpen):
        rules.add_participant_after_draw(session, circle, "3")


def test_add_rejects_someone_already_in(session):
    circle = drawn_circle(session, 4)

    with pytest.raises(rules.AlreadyJoined):
        rules.add_participant_after_draw(session, circle, "3")
