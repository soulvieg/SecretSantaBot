from datetime import timedelta

import pytest
import sqlalchemy as sa

from db import rules
from db.models import Assignment, ContactInfo, Exclusion, Shipment, WishlistItem


def test_close_deletes_personal_data_and_keeps_assignments(session, make_user, make_circle, make_participant):
    owner = make_user("100")
    circle = make_circle(owner=owner)
    giver = make_participant(circle, ready=True)
    receiver = make_participant(circle, ready=True)
    rules.save_contact(session, giver, {"address": "Via Roma 1", "city_zip": "10100 Torino"})
    rules.add_wishlist_item(session, giver, title="Sciarpa", price=1500)
    rules.replace_exclusions(session, circle, giver, [receiver.id])
    assignment = Assignment(
        circle_id=circle.id,
        round=1,
        giver_participant_id=giver.id,
        receiver_participant_id=receiver.id,
    )
    session.add(assignment)
    session.flush()
    session.add(Shipment(assignment_id=assignment.id, carrier="Poste"))
    session.flush()

    rules.close_circle(session, circle, "100")

    assert circle.status == "closed"
    assert session.scalar(sa.select(sa.func.count()).select_from(ContactInfo)) == 0
    assert session.scalar(sa.select(sa.func.count()).select_from(WishlistItem)) == 0
    assert session.scalar(sa.select(sa.func.count()).select_from(Exclusion)) == 0
    assert session.scalar(sa.select(sa.func.count()).select_from(Shipment)) == 0
    assert session.scalar(sa.select(sa.func.count()).select_from(Assignment)) == 1


def test_close_leaves_other_circles_alone(session, make_user, make_circle, make_participant):
    owner = make_user("100")
    closing = make_circle(owner=owner, name="Closing")
    other = make_circle(owner=owner, name="Other")
    mine = make_participant(closing)
    theirs = make_participant(other)
    rules.save_contact(session, mine, {"address": "A", "city_zip": "B"})
    rules.save_contact(session, theirs, {"address": "C", "city_zip": "D"})

    rules.close_circle(session, closing, "100")

    assert rules.load_contact(session, mine) is None
    assert rules.load_contact(session, theirs) is not None
    assert other.status == "open"


def test_close_rejects_non_owner(session, make_user, make_circle):
    owner = make_user("100")
    make_user("200")
    circle = make_circle(owner=owner)

    with pytest.raises(rules.NotOwner):
        rules.close_circle(session, circle, "200")

    assert circle.status == "open"


def test_close_rejects_already_closed_circle(session, make_user, make_circle):
    owner = make_user("100")
    circle = make_circle(owner=owner)
    circle.status = "closed"
    session.flush()

    with pytest.raises(rules.AlreadyClosed):
        rules.close_circle(session, circle, "100")


def test_due_open_circles_only_returns_expired_open_ones(session, make_circle):
    now = rules.utc_to_now()
    expired = make_circle(name="Expired")
    expired.signup_deadline = now - timedelta(minutes=1)
    later = make_circle(name="Later")
    later.signup_deadline = now + timedelta(days=1)
    drawn = make_circle(name="Drawn")
    drawn.status = "drawn"
    drawn.signup_deadline = now - timedelta(days=1)
    no_deadline = make_circle(name="NoDeadline")
    session.flush()

    assert rules.due_open_circles(session, now) == [expired.id]
    assert no_deadline.signup_deadline is None


def test_stale_drawn_circles_respects_the_grace_period(session, make_circle):
    now = rules.utc_to_now()
    old = make_circle(name="Old")
    old.status = "drawn"
    old.exchange_date = now - timedelta(days=20)
    recent = make_circle(name="Recent")
    recent.status = "drawn"
    recent.exchange_date = now - timedelta(days=1)
    collecting = make_circle(name="Collecting")
    collecting.status = "collecting"
    collecting.exchange_date = now - timedelta(days=20)
    session.flush()

    assert rules.stale_drawn_circles(session, now - timedelta(days=14)) == [old.id]
