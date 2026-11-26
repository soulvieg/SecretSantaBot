from cogs.gift import reveal_embed
from db import rules


def _ship_to(embed) -> str:
    return next(field.value for field in embed.fields if field.name == "Ship to")


def test_update_contact_merges_partial_fields(session, make_circle, make_participant):
    circle = make_circle()
    participant = make_participant(circle)

    rules.update_contact(session, participant, {"street": "Via Roma", "street_number": "1"})
    rules.update_contact(session, participant, {"city": "Torino", "zip": "10100"})

    assert rules.load_contact(session, participant) == {
        "street": "Via Roma",
        "street_number": "1",
        "city": "Torino",
        "zip": "10100",
    }


def test_update_contact_drops_fields_left_empty(session, make_circle, make_participant):
    circle = make_circle()
    participant = make_participant(circle)

    rules.update_contact(
        session, participant, {"street": "Via Roma", "city": "Torino", "phone": "123"}
    )
    rules.update_contact(session, participant, {"city": "", "phone": ""})

    assert rules.load_contact(session, participant) == {"street": "Via Roma"}


def test_reveal_embed_formats_split_address():
    embed = reveal_embed(
        circle_name="Xmas",
        budget=2500,
        currency="EUR",
        giftee_id="42",
        contact={
            "street": "Via Roma",
            "street_number": "1",
            "zip": "10100",
            "city": "Torino",
            "phone": "333",
        },
        items=[],
    )

    assert _ship_to(embed) == "Via Roma 1, 10100 Torino"


def test_reveal_embed_without_address_still_shows_extras():
    embed = reveal_embed(
        circle_name="Xmas",
        budget=None,
        currency="EUR",
        giftee_id="42",
        contact={"digital": "steam: soul"},
        items=[],
    )

    assert "No address on file" in _ship_to(embed)
    assert any(field.name == "Digital contact" for field in embed.fields)


def test_reveal_embed_shows_steam_wishlist():
    link = "https://store.steampowered.com/wishlist/id/soul/"
    embed = reveal_embed(
        circle_name="Xmas",
        budget=None,
        currency="EUR",
        giftee_id="42",
        contact={"steam": link},
        items=[],
    )

    steam = next(field for field in embed.fields if field.name == "Steam wishlist")
    assert steam.value == link


def test_refresh_button_carries_the_assignment():
    from cogs.gift import RefreshButton

    item = RefreshButton(7).item
    assert item.custom_id == "santa:reveal:7"


def _wishlist_field(embed) -> str:
    return next(field.value for field in embed.fields if field.name == "Wishlist")


def test_reveal_payload_picks_up_new_items_and_steam(
    session, make_circle, make_participant
):
    from cogs.gift import _reveal_payload
    from db.models import Assignment

    circle = make_circle()
    giver = make_participant(circle)
    receiver = make_participant(circle)
    assignment = Assignment(
        circle_id=circle.id,
        round=1,
        giver_participant_id=giver.id,
        receiver_participant_id=receiver.id,
    )
    session.add(assignment)
    session.flush()

    before = _reveal_payload(session, assignment)
    assert before is not None
    assert "Steam gift card" not in _wishlist_field(before[1])

    rules.add_wishlist_item(session, receiver, title="Steam gift card")
    rules.update_contact(session, receiver, {"steam": "https://steam.test/wishlist"})
    after = _reveal_payload(session, assignment)

    assert after is not None
    assert "Steam gift card" in _wishlist_field(after[1])
    steam = next(field for field in after[1].fields if field.name == "Steam wishlist")
    assert steam.value == "https://steam.test/wishlist"
