import re
import time
from typing import Self

import discord
import sqlalchemy as sa
from discord.ext import commands
from sqlalchemy.orm import Session

from db.engine import get_session
from db.models import Assignment, Circle, Participant, Shipment, User
from db.rules import (
    DrawImpossible,
    draw_circle,
    load_contact,
    utc_to_now,
    wishlist_items,
)

WishlistEntry = tuple[str, str | None, int | None, str | None]

RELAY_MAX_LENGTH = 1000
RELAY_COOLDOWN_SECONDS = 20

# In memory on purpose: a bot restart just resets the cooldowns.
_last_relay: dict[int, float] = {}


def reveal_embed(
    *,
    circle_name: str,
    budget: int | None,
    currency: str,
    giftee_id: str,
    contact: dict | None,
    items: list[WishlistEntry],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎁 Your giftee for {circle_name}",
        color=discord.Color.green(),
        description=f"You are the Secret Santa of <@{giftee_id}>. Keep it a secret!",
    )
    if budget:
        embed.add_field(name="Budget", value=f"{budget / 100:.2f} {currency}", inline=True)

    if contact is None:
        embed.add_field(
            name="Ship to",
            value="⚠️ No address on file. Ask the organizer.",
            inline=False,
        )
    else:
        home = ", ".join(
            part for part in (contact.get("address"), contact.get("city_zip")) if part
        )
        embed.add_field(name="Ship to", value=home or "⚠️ Missing", inline=False)
        if contact.get("phone"):
            embed.add_field(name="Phone", value=str(contact["phone"]), inline=True)
        if contact.get("digital"):
            embed.add_field(name="Digital contact", value=str(contact["digital"]), inline=True)
        if contact.get("notes"):
            embed.add_field(name="Notes", value=str(contact["notes"]), inline=False)

    if items:
        lines: list[str] = []
        for title, url, price, note in items:
            line = f"• {title}"
            if price:
                line += f" — {price / 100:.2f} {currency}"
            if url:
                line += f"\n  {url}"
            if note:
                line += f"\n  {note}"
            lines.append(line)
        embed.add_field(name="Wishlist", value="\n".join(lines)[:1020], inline=False)
    else:
        embed.add_field(name="Wishlist", value="No wishlist submitted.", inline=False)

    return embed


def reveal_view(assignment_id: int) -> discord.ui.View:
    """The two buttons that live in the reveal DM: relay and shipment."""
    view = discord.ui.View(timeout=None)
    view.add_item(RelayButton(assignment_id, "giftee"))
    view.add_item(ShippedButton(assignment_id))
    return view


def _reveal_payload(session: Session, assignment: Assignment) -> tuple[str, discord.Embed] | None:
    circle = session.get(Circle, assignment.circle_id)
    giver = session.get(Participant, assignment.giver_participant_id)
    receiver = session.get(Participant, assignment.receiver_participant_id)
    if circle is None or giver is None or receiver is None:
        return None
    giver_user = session.get(User, giver.user_id)
    receiver_user = session.get(User, receiver.user_id)
    if giver_user is None or not giver_user.discord_id:
        return None
    if receiver_user is None or not receiver_user.discord_id:
        return None
    embed = reveal_embed(
        circle_name=circle.name,
        budget=circle.budget,
        currency=circle.currency,
        giftee_id=receiver_user.discord_id,
        contact=load_contact(session, receiver),
        items=[
            (item.title, item.url, item.price, item.note)
            for item in wishlist_items(session, receiver)
        ],
    )
    return giver_user.discord_id, embed


async def send_reveal(bot: discord.Client, assignment_id: int) -> tuple[bool, str]:
    """DM the assignment to its giver. Returns (delivered, giver_discord_id)."""
    with get_session() as session:
        assignment = session.get(Assignment, assignment_id)
        if assignment is None:
            return False, ""
        payload = _reveal_payload(session, assignment)
    if payload is None:
        return False, ""
    discord_id, embed = payload
    try:
        user = await bot.fetch_user(int(discord_id))
        await user.send(embed=embed, view=reveal_view(assignment_id))
    except (ValueError, discord.HTTPException):
        return False, discord_id
    return True, discord_id


async def refresh_reveal_for(
    bot: discord.Client, circle_id: int, receiver_participant_id: int
) -> tuple[bool, str]:
    """Send again the reveal to whoever is giving to this participant."""
    with get_session() as session:
        circle = session.get(Circle, circle_id)
        if circle is None or circle.status != "drawn":
            return False, ""
        assignment = session.scalar(
            sa.select(Assignment).where(
                Assignment.circle_id == circle.id,
                Assignment.round == circle.current_round,
                Assignment.receiver_participant_id == receiver_participant_id,
            )
        )
        if assignment is None:
            return False, ""
        assignment_id = assignment.id
    return await send_reveal(bot, assignment_id)


async def run_draw(bot: discord.Client, circle_id: int) -> tuple[str, list[str]]:
    """Draw the round and DM every giver.

    Returns (status, failed_discord_ids) where status is one of
    "drawn", "impossible", "already", "gone".
    """
    try:
        with get_session() as session:
            circle = session.get(Circle, circle_id)
            if circle is None:
                return "gone", []
            pairing = draw_circle(session, circle)
            if pairing is None:
                return "already", []
            latest = session.scalar(
                sa.select(sa.func.max(Assignment.round)).where(
                    Assignment.circle_id == circle.id
                )
            )
            assignment_ids = list(
                session.scalars(
                    sa.select(Assignment.id).where(
                        Assignment.circle_id == circle.id,
                        Assignment.round == latest,
                    )
                )
            )
    except DrawImpossible:
        return "impossible", []

    failed: list[str] = []
    for assignment_id in assignment_ids:
        delivered, discord_id = await send_reveal(bot, assignment_id)
        if not delivered and discord_id:
            failed.append(discord_id)
    return "drawn", failed


class RelayButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"santa:relay:(?P<assignment>\d+):(?P<target>giftee|giver)",
):
    """Anonymous relay. The target in the custom_id is who receives the message."""

    def __init__(self, assignment_id: int, target: str) -> None:
        super().__init__(
            discord.ui.Button(
                label="Message your giftee" if target == "giftee" else "Reply",
                style=discord.ButtonStyle.primary,
                custom_id=f"santa:relay:{assignment_id}:{target}",
            )
        )
        self.assignment_id = assignment_id
        self.target = target

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Item,
        match: re.Match[str],
        /,
    ) -> Self:
        return cls(int(match["assignment"]), match["target"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(RelayModal(self.assignment_id, self.target))


class ShippedButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"santa:ship:(?P<assignment>\d+)",
):
    def __init__(self, assignment_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="I shipped it",
                style=discord.ButtonStyle.secondary,
                custom_id=f"santa:ship:{assignment_id}",
            )
        )
        self.assignment_id = assignment_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Item,
        match: re.Match[str],
        /,
    ) -> Self:
        return cls(int(match["assignment"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ShipmentModal(self.assignment_id))


class RelayModal(discord.ui.Modal, title="Write a message"):
    message = discord.ui.TextInput(
        label="Message",
        style=discord.TextStyle.paragraph,
        max_length=RELAY_MAX_LENGTH,
    )

    def __init__(self, assignment_id: int, target: str) -> None:
        super().__init__()
        self.assignment_id = assignment_id
        self.target = target

    async def on_submit(self, interaction: discord.Interaction) -> None:
        text = self.message.value.strip()
        if not text:
            await interaction.response.send_message("The message is empty.", ephemeral=True)
            return

        now = time.monotonic()
        previous = _last_relay.get(interaction.user.id)
        if previous is not None and now - previous < RELAY_COOLDOWN_SECONDS:
            wait = int(RELAY_COOLDOWN_SECONDS - (now - previous)) + 1
            await interaction.response.send_message(
                f"Slow down: try again in {wait} seconds.", ephemeral=True
            )
            return

        target_discord_id: str | None = None
        with get_session() as session:
            assignment = session.get(Assignment, self.assignment_id)
            if assignment is not None:
                circle = session.get(Circle, assignment.circle_id)
                if circle is not None and circle.status == "drawn":
                    if self.target == "giftee":
                        participant_id = assignment.receiver_participant_id
                    else:
                        participant_id = assignment.giver_participant_id
                    participant = session.get(Participant, participant_id)
                    if participant is not None:
                        user = session.get(User, participant.user_id)
                        if user is not None and user.discord_id:
                            target_discord_id = user.discord_id

        if target_discord_id is None:
            await interaction.response.send_message(
                "This exchange is over or changed. Ask the organizer.", ephemeral=True
            )
            return

        header = "💬 Your Secret Santa says:" if self.target == "giftee" else "💬 Your giftee replied:"
        reply = discord.ui.View(timeout=None)
        reply.add_item(RelayButton(self.assignment_id, "giver" if self.target == "giftee" else "giftee"))
        try:
            user = await interaction.client.fetch_user(int(target_discord_id))
            await user.send(
                f"{header}\n\n{text}",
                view=reply,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (ValueError, discord.HTTPException):
            await interaction.response.send_message(
                "I couldn't DM them: their DMs are closed.", ephemeral=True
            )
            return

        _last_relay[interaction.user.id] = now
        await interaction.response.send_message("Delivered.", ephemeral=True)


class ShipmentModal(discord.ui.Modal, title="Shipping details"):
    carrier = discord.ui.TextInput(
        label="Carrier", max_length=128, placeholder="Poste, DHL, ..."
    )
    tracking = discord.ui.TextInput(
        label="Tracking number (optional)", required=False, max_length=256
    )

    def __init__(self, assignment_id: int) -> None:
        super().__init__()
        self.assignment_id = assignment_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        carrier = self.carrier.value.strip()
        tracking = (self.tracking.value or "").strip() or None
        if not carrier:
            await interaction.response.send_message("The carrier can't be empty.", ephemeral=True)
            return

        state = "invalid"
        updated = False
        receiver_discord_id: str | None = None
        with get_session() as session:
            assignment = session.get(Assignment, self.assignment_id)
            if assignment is not None:
                circle = session.get(Circle, assignment.circle_id)
                if circle is not None and circle.status == "drawn":
                    stored = session.get(Shipment, assignment.id)
                    updated = stored is not None
                    if stored is None:
                        session.add(
                            Shipment(
                                assignment_id=assignment.id,
                                carrier=carrier,
                                tracking_number=tracking,
                            )
                        )
                    else:
                        stored.carrier = carrier
                        stored.tracking_number = tracking
                        stored.updated_at = utc_to_now()
                    receiver = session.get(Participant, assignment.receiver_participant_id)
                    user = session.get(User, receiver.user_id) if receiver is not None else None
                    if user is not None and user.discord_id:
                        receiver_discord_id = user.discord_id
                    state = "ok"

        if state != "ok":
            await interaction.response.send_message(
                "This exchange is over or changed. Ask the organizer.", ephemeral=True
            )
            return
        if updated:
            await interaction.response.send_message("Shipping details updated.", ephemeral=True)
            return
        if receiver_discord_id is None:
            await interaction.response.send_message("Saved.", ephemeral=True)
            return

        text = f"🎁 Your Secret Santa shipped your gift via **{carrier}**."
        if tracking:
            text += f"\nTracking: `{tracking}`"
        try:
            user = await interaction.client.fetch_user(int(receiver_discord_id))
            await user.send(text, allowed_mentions=discord.AllowedMentions.none())
        except (ValueError, discord.HTTPException):
            await interaction.response.send_message(
                "Saved, but I couldn't DM your giftee.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "Saved. Your giftee was told the gift is on the way.", ephemeral=True
        )


class Gift(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        # Buttons in old DMs keep working after a restart.
        self.bot.add_dynamic_items(RelayButton, ShippedButton)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Gift(bot))
