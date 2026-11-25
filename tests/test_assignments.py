import random

import pytest
import sqlalchemy as sa

from db import rules
from db.models import Assignment


def prepare(session, count: int):
    """A collecting circle with `count` ready participants (owner included)."""
    circle = rules.create_circle(session, name="Xmas", owner_id="100", discord_server_id=1)
    for discord_id in range(2, count + 1):
        rules.join_circle(session, circle, str(discord_id))
    for participant in rules.active_participants(session, circle.id):
        rules.set_ready(session, participant)
    rules.close_signup(session, circle, "100")
    session.flush()
    session.refresh(circle)
    return circle


def assignments(session, circle_id: int) -> list[Assignment]:
    return list(
        session.scalars(sa.select(Assignment).where(Assignment.circle_id == circle_id))
    )


def test_draw_writes_one_assignment_per_participant(session):
    circle = prepare(session, 4)

    pairing = rules.draw_circle(session, circle, random.Random(1))

    assert pairing is not None
    rows = assignments(session, circle.id)
    assert len(rows) == 4
    assert {row.round for row in rows} == {1}
    assert {row.giver_participant_id for row in rows} == set(pairing)
    assert {row.receiver_participant_id for row in rows} == set(pairing.values())
    session.refresh(circle)
    assert circle.status == "drawn"
    assert circle.current_round == 1


def test_draw_never_pairs_people_with_themselves(session):
    circle = prepare(session, 6)

    rules.draw_circle(session, circle, random.Random(3))

    for row in assignments(session, circle.id):
        assert row.giver_participant_id != row.receiver_participant_id


def test_second_draw_is_rejected(session):
    circle = prepare(session, 4)
    assert rules.draw_circle(session, circle, random.Random(1)) is not None

    assert rules.draw_circle(session, circle, random.Random(2)) is None
    assert len(assignments(session, circle.id)) == 4


def test_draw_needs_three_participants(session):
    circle = prepare(session, 2)

    with pytest.raises(rules.DrawImpossible):
        rules.draw_circle(session, circle, random.Random(1))

    session.refresh(circle)
    assert circle.status == "collecting"
    assert assignments(session, circle.id) == []


def test_draw_impossible_keeps_the_circle_collecting(session):
    circle = prepare(session, 3)
    participants = rules.active_participants(session, circle.id)
    rules.replace_exclusions(
        session, circle, participants[0], [participant.id for participant in participants[1:]]
    )

    with pytest.raises(rules.DrawImpossible):
        rules.draw_circle(session, circle, random.Random(1))

    session.refresh(circle)
    assert circle.status == "collecting"
    assert circle.current_round == 0
    assert assignments(session, circle.id) == []


def test_draw_respects_exclusions(session):
    circle = prepare(session, 5)
    participants = rules.active_participants(session, circle.id)
    first = participants[0]
    excluded = [participants[1].id, participants[2].id]
    rules.replace_exclusions(session, circle, first, excluded)

    rules.draw_circle(session, circle, random.Random(5))

    for row in assignments(session, circle.id):
        if row.giver_participant_id == first.id:
            assert row.receiver_participant_id not in excluded


def test_draw_rejected_when_signups_are_still_open(session):
    circle = rules.create_circle(session, name="Open", owner_id="100", discord_server_id=1)
    for discord_id in (2, 3):
        rules.join_circle(session, circle, str(discord_id))

    assert rules.draw_circle(session, circle, random.Random(1)) is None
    session.refresh(circle)
    assert circle.status == "open"
    assert assignments(session, circle.id) == []
