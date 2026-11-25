import pytest

from db import rules
from db.models import ContactInfo, Exclusion, WishlistItem


def test_all_ready_needs_three_participants(session, make_circle, make_participant):
    circle = make_circle()
    make_participant(circle, ready=True)
    make_participant(circle, ready=True)

    assert rules.all_ready(session, circle.id) is False


def test_all_ready_true_when_three_ready(session, make_circle, make_participant):
    circle = make_circle()
    for _ in range(3):
        make_participant(circle, ready=True)

    assert rules.all_ready(session, circle.id) is True


def test_all_ready_false_when_one_is_pending(session, make_circle, make_participant):
    circle = make_circle()
    make_participant(circle, ready=True)
    make_participant(circle, ready=True)
    make_participant(circle, ready=False)

    assert rules.all_ready(session, circle.id) is False


def test_all_ready_ignores_withdrawn(session, make_circle, make_participant):
    circle = make_circle()
    for _ in range(3):
        make_participant(circle, ready=True)
    gone = make_participant(circle, ready=False)
    gone.withdrawn_at = rules.utc_to_now()
    session.flush()

    assert rules.all_ready(session, circle.id) is True


def test_all_ready_ignores_other_circles(session, make_circle, make_participant):
    circle = make_circle()
    other = make_circle(name="Other")
    for _ in range(3):
        make_participant(circle, ready=True)
    make_participant(other, ready=False)

    assert rules.all_ready(session, circle.id) is True


def test_set_ready_toggles(session, make_circle, make_participant):
    participant = make_participant(make_circle())

    rules.set_ready(session, participant)

    assert participant.ready is True

    rules.set_ready(session, participant, False)

    assert participant.ready is False


def test_try_mark_drawn_only_succeeds_once(session, make_circle):
    circle = make_circle()
    circle.status = "collecting"
    session.flush()

    assert rules.try_mark_drawn(session, circle.id) is True
    assert circle.status == "drawn"
    assert circle.current_round == 1

    assert rules.try_mark_drawn(session, circle.id) is False
    assert circle.current_round == 1


def test_try_mark_drawn_rejects_open_circle(session, make_circle):
    circle = make_circle()
    circle.status = "open"
    session.flush()

    assert rules.try_mark_drawn(session, circle.id) is False
    assert circle.status == "open"


def test_panel_message_roundtrip(session, make_circle, make_participant):
    participant = make_participant(make_circle())

    rules.set_panel_message(session, participant, 999)

    found = rules.participant_from_panel(session, 999)
    assert found is not None
    assert found.id == participant.id


def test_participant_from_panel_unknown_id(session):
    assert rules.participant_from_panel(session, 123456) is None


def test_contact_roundtrip(session, make_circle, make_participant):
    participant = make_participant(make_circle())
    payload = {
        "address": "Via Roma 1",
        "city": "Milan",
        "zip": "10221",
        "phone": "+39 000 000 0000",
        "digital": {"platform": "steam", "id": "12345"},
    }

    assert rules.load_contact(session, participant) is None

    rules.save_contact(session, participant, payload)

    assert rules.load_contact(session, participant) == payload
    row = session.query(ContactInfo).filter_by(participant_id=participant.id).one()
    assert "Torino" not in row.payload


def test_save_contact_upserts_single_row(session, make_circle, make_participant):
    participant = make_participant(make_circle())

    rules.save_contact(session, participant, {"address": "Via Roma 1"})
    rules.save_contact(session, participant, {"address": "Via Tortora 2"})

    rows = session.query(ContactInfo).filter_by(participant_id=participant.id).all()
    assert len(rows) == 1
    assert rules.load_contact(session, participant) == {"address": "Via Tortora 2"}


def test_add_wishlist_item_appends_positions(session, make_circle, make_participant):
    participant = make_participant(make_circle())

    for title in ("Lamp", "Mug", "Book"):
        rules.add_wishlist_item(session, participant, title=title)

    items = session.query(WishlistItem).filter_by(participant_id=participant.id).order_by(WishlistItem.position).all()
    assert [item.title for item in items] == ["Lamp", "Mug", "Book"]
    assert [item.position for item in items] == [0, 1, 2]
    assert rules.wishlist_count(session, participant.id) == 3


def test_add_wishlist_item_keeps_optional_fields(session, make_circle, make_participant):
    participant = make_participant(make_circle())

    item = rules.add_wishlist_item(
        session,
        participant,
        title="Lamp",
        url="https://example.com/lamp",
        price=2500,
        note="green if possible",
    )

    assert item.url == "https://example.com/lamp"
    assert item.price == 2500
    assert item.note == "green if possible"


def test_replace_exclusions_replaces_previous_set(session, make_circle, make_participant):
    circle = make_circle()
    giver = make_participant(circle)
    first = make_participant(circle)
    second = make_participant(circle)

    rules.replace_exclusions(session, circle, giver, [first.id])
    rules.replace_exclusions(session, circle, giver, [second.id])

    assert rules.exclusion_ids(session, giver) == [second.id]


def test_replace_exclusions_dedups_and_skips_self(session, make_circle, make_participant):
    circle = make_circle()
    giver = make_participant(circle)
    other = make_participant(circle)

    rules.replace_exclusions(session, circle, giver, [other.id, other.id, giver.id])

    rows = session.query(Exclusion).filter_by(giver_participant_id=giver.id).all()
    assert len(rows) == 1
    assert rows[0].excluded_participant_id == other.id


def test_replace_exclusions_ignores_foreign_participants(session, make_circle, make_participant):
    circle = make_circle()
    other_circle = make_circle(name="Other")
    giver = make_participant(circle)
    stranger = make_participant(other_circle)

    rules.replace_exclusions(session, circle, giver, [stranger.id])

    assert rules.exclusion_ids(session, giver) == []


def test_replace_exclusions_ignores_withdrawn(session, make_circle, make_participant):
    circle = make_circle()
    giver = make_participant(circle)
    gone = make_participant(circle)
    gone.withdrawn_at = rules.utc_to_now()
    session.flush()

    rules.replace_exclusions(session, circle, giver, [gone.id])

    assert rules.exclusion_ids(session, giver) == []


def test_exclusion_ids_ordered_by_insertion(session, make_circle, make_participant):
    circle = make_circle()
    giver = make_participant(circle)
    first = make_participant(circle)
    second = make_participant(circle)

    rules.replace_exclusions(session, circle, giver, [first.id, second.id])

    assert rules.exclusion_ids(session, giver) == [first.id, second.id]


def test_exclusion_ids_empty_when_none(session, make_circle, make_participant):
    giver = make_participant(make_circle())

    assert rules.exclusion_ids(session, giver) == []


def test_replace_exclusions_with_empty_list_clears(session, make_circle, make_participant):
    circle = make_circle()
    giver = make_participant(circle)
    other = make_participant(circle)
    rules.replace_exclusions(session, circle, giver, [other.id])

    rules.replace_exclusions(session, circle, giver, [])

    assert rules.exclusion_ids(session, giver) == []


def test_join_circle_after_withdraw_clears_flag(session, make_circle):
    circle = make_circle()

    rules.join_circle(session, circle, "2")
    rules.leave_circle(session, circle, "2")
    participant = rules.join_circle(session, circle, "2")

    assert participant.withdrawn_at is None


def test_create_circle_joins_owner(session):
    circle = rules.create_circle(session, name="Xmas", owner_id="42", discord_server_id=1)

    participants = rules.active_participants(session, circle.id)
    assert len(participants) == 1
    assert participants[0].user_id == rules.get_user(session, "42").id


def test_leave_circle_rejects_owner(session):
    circle = rules.create_circle(session, name="Xmas", owner_id="42", discord_server_id=1)

    with pytest.raises(rules.OwnerCannotLeave):
        rules.leave_circle(session, circle, "42")


def test_leave_circle_allows_other_participant(session):
    circle = rules.create_circle(session, name="Xmas", owner_id="42", discord_server_id=1)
    rules.join_circle(session, circle, "43")

    rules.leave_circle(session, circle, "43")

    assert rules.active_count(session, circle.id) == 1


def test_active_participants_ignores_withdrawn(session, make_circle, make_participant):
    circle = make_circle()
    stays = make_participant(circle)
    gone = make_participant(circle)
    gone.withdrawn_at = rules.utc_to_now()
    session.flush()

    assert [participant.id for participant in rules.active_participants(session, circle.id)] == [stays.id]


@pytest.mark.parametrize("status", ["collecting", "drawn"])
def test_join_and_leave_rejected_after_open(session, make_circle, status):
    circle = make_circle()
    circle.status = status
    session.flush()

    with pytest.raises(rules.GroupNotOpen):
        rules.join_circle(session, circle, "1")
    with pytest.raises(rules.GroupNotOpen):
        rules.leave_circle(session, circle, "1")
