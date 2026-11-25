import discord
from discord.ext import commands
from sqlalchemy.orm import Session

from cogs.gift import refresh_reveal_for, run_draw, send_reveal
from db.engine import get_session
from db.models import Circle, Participant, User
from db.rules import (
    GroupNotOpen,
    NotJoined,
    OwnerCannotLeave,
    active_count,
    active_participants,
    add_wishlist_item,
    all_ready,
    assignment_for,
    exclusion_ids,
    leave_any_time,
    load_contact,
    owner_discord_id,
    participant_from_panel,
    replace_exclusions,
    save_contact,
    set_panel_message,
    set_ready,
    wishlist_count,
)

MAX_WISHLIST_ITEMS = 20
MAX_EXCLUSIONS = 2
MAX_EXCLUSION_OPTIONS = 25  # hard limit of a Discord select menu
MIN_PARTICIPANTS_FOR_EXCLUSIONS = 5


def participant_id_from(interaction: discord.Interaction) -> int | None:
    """Resolve the participant from the panel message the component lives in."""
    if interaction.message is None:
        return None
    with get_session() as session:
        found = participant_from_panel(session, interaction.message.id)
        return found.id if found is not None else None


def render_panel(
    session: Session, participant: Participant, circle: Circle
) -> tuple[discord.Embed, "PanelView"]:
    has_contact = load_contact(session, participant) is not None
    items = wishlist_count(session, participant.id)
    excludes = exclusion_ids(session, participant)
    uses_exclusions = (
        circle.avoid_repeat
        and active_count(session, circle.id) >= MIN_PARTICIPANTS_FOR_EXCLUSIONS
    )

    embed = discord.Embed(title=f"🎅 {circle.name}", color=discord.Color.red())
    embed.description = (
        "Fill in your details, then press **Done**. "
        "Your address is only shown to whoever draws your name."
    )
    if circle.status == "drawn":
        embed.description = (
            "Names are drawn: check your DMs for your giftee. "
            "You can still update your info if something changes."
        )
    embed.add_field(
        name="Contact info",
        value="✅ saved" if has_contact else "❌ missing",
        inline=True,
    )
    embed.add_field(
        name="Wishlist",
        value=f"{items}/{MAX_WISHLIST_ITEMS} items" if items else "❌ none yet",
        inline=True,
    )
    if uses_exclusions:
        embed.add_field(
            name="Past gifts",
            value=f"{len(excludes)} excluded" if excludes else "none",
            inline=True,
        )
    embed.add_field(
        name="Ready",
        value="✅ yes" if participant.ready else "not yet",
        inline=True,
    )
    return embed, PanelView()


async def refresh_panel(interaction: discord.Interaction, participant_id: int) -> None:
    """Re-render the stored panel message. Writes are committed before the edit."""
    with get_session() as session:
        participant = session.get(Participant, participant_id)
        if participant is None or participant.panel_msg_id is None:
            return
        circle = session.get(Circle, participant.circle_id)
        if circle is None:
            return
        panel_id = participant.panel_msg_id
        embed, view = render_panel(session, participant, circle)

    channel = interaction.channel
    if not isinstance(channel, discord.DMChannel):
        return
    try:
        await channel.get_partial_message(panel_id).edit(embed=embed, view=view)
    except discord.HTTPException:
        pass


async def send_panels(
    bot: commands.Bot, circle_id: int, targets: list[tuple[int, str]]
) -> tuple[int, list[str]]:
    """Send the setup panel by DM to every target. Returns (sent, failed_discord_ids)."""
    sent = 0
    failed: list[str] = []
    for participant_id, discord_id in targets:
        with get_session() as session:
            participant = session.get(Participant, participant_id)
            circle = session.get(Circle, circle_id)
            if participant is None or circle is None:
                continue
            embed, view = render_panel(session, participant, circle)

        try:
            user = await bot.fetch_user(int(discord_id))
            message = await user.send(embed=embed, view=view)
        except (ValueError, discord.HTTPException):
            failed.append(discord_id)
            continue

        with get_session() as session:
            stored = session.get(Participant, participant_id)
            if stored is not None:
                set_panel_message(session, stored, message.id)
        sent += 1
    return sent, failed


class PanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Contact info",
        style=discord.ButtonStyle.primary,
        custom_id="santa:panel:contact",
    )
    async def contact(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        participant_id = participant_id_from(interaction)
        if participant_id is None:
            await interaction.response.send_message(
                "This panel is no longer valid.", ephemeral=True
            )
            return
        await interaction.response.send_modal(ContactModal(participant_id))

    @discord.ui.button(
        label="Wishlist",
        style=discord.ButtonStyle.primary,
        custom_id="santa:panel:wishlist",
    )
    async def wishlist(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        participant_id = participant_id_from(interaction)
        if participant_id is None:
            await interaction.response.send_message(
                "This panel is no longer valid.", ephemeral=True
            )
            return
        with get_session() as session:
            full = wishlist_count(session, participant_id) >= MAX_WISHLIST_ITEMS
        if full:
            await interaction.response.send_message(
                "Your wishlist is full. Remove an item before adding another.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(WishlistModal(participant_id))

    @discord.ui.button(
        label="Past gifts",
        style=discord.ButtonStyle.secondary,
        custom_id="santa:panel:past",
    )
    async def past(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        participant_id = participant_id_from(interaction)
        if participant_id is None:
            await interaction.response.send_message(
                "This panel is no longer valid.", ephemeral=True
            )
            return

        allowed = False
        guild_id = 0
        already: list[int] = []
        others: list[tuple[int, str]] = []
        with get_session() as session:
            participant = session.get(Participant, participant_id)
            if participant is not None:
                circle = session.get(Circle, participant.circle_id)
                if circle is not None:
                    allowed = (
                        circle.avoid_repeat
                        and active_count(session, circle.id)
                        >= MIN_PARTICIPANTS_FOR_EXCLUSIONS
                    )
                    guild_id = circle.discord_server_id
                    if allowed:
                        already = exclusion_ids(session, participant)
                        for other in active_participants(session, circle.id):
                            if other.id == participant_id:
                                continue
                            user = session.get(User, other.user_id)
                            if user is None or not user.discord_id:
                                continue
                            others.append((other.id, user.discord_id))

        if not allowed:
            await interaction.response.send_message(
                "This event doesn't use exclusions.", ephemeral=True
            )
            return
        if len(others) > MAX_EXCLUSION_OPTIONS:
            await interaction.response.send_message(
                "There are too many participants to list here. Ask the organizer.",
                ephemeral=True,
            )
            return

        # Member lookups can take longer than the 3 second interaction window.
        await interaction.response.defer(ephemeral=True)

        guild = interaction.client.get_guild(guild_id)
        if guild is None:
            await interaction.followup.send(
                "I can't reach that server right now.", ephemeral=True
            )
            return

        options: list[discord.SelectOption] = []
        for other_id, other_discord_id in others:
            try:
                member = await guild.fetch_member(int(other_discord_id))
            except (ValueError, discord.HTTPException):
                member = None
            label = member.display_name if member is not None else f"User {other_discord_id}"
            options.append(
                discord.SelectOption(
                    label=label, value=str(other_id), default=other_id in already
                )
            )

        await interaction.followup.send(
            "Pick up to two people you'd rather not be drawn for. "
            "Sending an empty selection clears the list.",
            view=ExclusionView(participant_id, options),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Done",
        style=discord.ButtonStyle.success,
        custom_id="santa:panel:done",
    )
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        participant_id = participant_id_from(interaction)
        if participant_id is None:
            await interaction.response.send_message(
                "This panel is no longer valid.", ephemeral=True
            )
            return

        state = "invalid"
        everyone = False
        trigger = False
        circle_id = 0
        with get_session() as session:
            participant = session.get(Participant, participant_id)
            if participant is not None:
                circle = session.get(Circle, participant.circle_id)
                if circle is None:
                    state = "gone"
                elif load_contact(session, participant) is None:
                    state = "no_contact"
                elif circle.status == "closed":
                    state = "closed"
                else:
                    set_ready(session, participant)
                    everyone = all_ready(session, circle.id)
                    circle_id = circle.id
                    trigger = circle.status == "collecting"
                    state = "ready"

        if state == "invalid":
            await interaction.response.send_message(
                "This panel is no longer valid.", ephemeral=True
            )
            return
        if state == "gone":
            await interaction.response.send_message(
                "This event no longer exists.", ephemeral=True
            )
            return
        if state == "closed":
            await interaction.response.send_message(
                "This event is closed.", ephemeral=True
            )
            return
        if state == "no_contact":
            await interaction.response.send_message(
                "Add your contact info first: the organizer needs an address to ship to.",
                ephemeral=True,
            )
            return

        if everyone and trigger:
            await interaction.response.send_message(
                "You're ready. Everyone is in, drawing the names...", ephemeral=True
            )
        elif everyone:
            await interaction.response.send_message("You're ready.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "You're ready. Waiting for the other participants.", ephemeral=True
            )
        await refresh_panel(interaction, participant_id)

        if not everyone or not trigger:
            return

        status, failed = await run_draw(interaction.client, circle_id)
        if status == "drawn":
            text = "Everyone is in. I drew the names: check your DMs."
            if failed:
                text += "\nI couldn't DM: " + ", ".join(
                    f"<@{discord_id}>" for discord_id in failed
                )
            await interaction.edit_original_response(content=text)
        elif status == "impossible":
            await interaction.edit_original_response(
                content=(
                    "Everyone is ready, but the exclusions leave no valid draw. "
                    "Relax some exclusions and press Done again."
                )
            )
        elif status == "already":
            await interaction.edit_original_response(
                content="The names were already drawn."
            )


    @discord.ui.button(
        label="Leave event",
        style=discord.ButtonStyle.danger,
        custom_id="santa:panel:leave",
    )
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        participant_id = participant_id_from(interaction)
        if participant_id is None:
            await interaction.response.send_message(
                "This panel is no longer valid.", ephemeral=True
            )
            return

        state = "invalid"
        donor: int | None = None
        circle_id = 0
        circle_name = ""
        owner = ""
        with get_session() as session:
            participant = session.get(Participant, participant_id)
            if participant is not None:
                circle = session.get(Circle, participant.circle_id)
                if circle is not None:
                    circle_id = circle.id
                    circle_name = circle.name
                    owner = owner_discord_id(session, circle)
                    try:
                        state, donor = leave_any_time(
                            session, circle, str(interaction.user.id)
                        )
                    except OwnerCannotLeave:
                        state = "owner"
                    except NotJoined:
                        state = "not_joined"
                    except GroupNotOpen:
                        state = "closed"

        if state == "invalid":
            await interaction.response.send_message(
                "This panel is no longer valid.", ephemeral=True
            )
            return
        if state == "owner":
            await interaction.response.send_message(
                "Organizers can't leave their own event. Close it with /santa close instead.",
                ephemeral=True,
            )
            return
        if state == "not_joined":
            await interaction.response.send_message(
                "You are not signed up for this event.", ephemeral=True
            )
            return
        if state == "closed":
            await interaction.response.send_message("This event is closed.", ephemeral=True)
            return

        if state == "spliced":
            await interaction.response.send_message(
                f"You left **{circle_name}**. The others were re-paired.", ephemeral=True
            )
            if donor is not None:
                with get_session() as session:
                    assignment = assignment_for(session, circle_id, donor)
                    assignment_id = assignment.id if assignment is not None else None
                if assignment_id is not None:
                    await send_reveal(interaction.client, assignment_id)
            return

        if state == "reset":
            await interaction.response.send_message(
                f"You left **{circle_name}**. Fewer than 3 people remain, so the draw "
                "was cancelled: everyone must press Done again.",
                ephemeral=True,
            )
            if owner:
                try:
                    user = await interaction.client.fetch_user(int(owner))
                    await user.send(
                        f"**{circle_name}** went back to collecting: someone left and the "
                        "round was cancelled. Ask the others to press Done again."
                    )
                except (ValueError, discord.HTTPException):
                    pass
            return

        await interaction.response.send_message(f"You left **{circle_name}**.", ephemeral=True)


class ExclusionSelect(discord.ui.Select):
    def __init__(self, participant_id: int, options: list[discord.SelectOption]) -> None:
        super().__init__(
            placeholder="Nobody selected",
            min_values=0,
            max_values=MAX_EXCLUSIONS,
            options=options,
        )
        self.participant_id = participant_id

    async def callback(self, interaction: discord.Interaction) -> None:
        chosen = [int(value) for value in self.values]
        state = "invalid"
        saved = 0
        with get_session() as session:
            participant = session.get(Participant, self.participant_id)
            if participant is not None:
                circle = session.get(Circle, participant.circle_id)
                if circle is not None:
                    replace_exclusions(session, circle, participant, chosen)
                    saved = len(exclusion_ids(session, participant))
                    state = "ok"

        if state != "ok":
            await interaction.response.send_message(
                "This panel is no longer valid.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"Saved: {saved} excluded." if saved else "Exclusion list cleared.",
            ephemeral=True,
        )
        await refresh_panel(interaction, self.participant_id)


class ExclusionView(discord.ui.View):
    def __init__(self, participant_id: int, options: list[discord.SelectOption]) -> None:
        # Not persistent on purpose: the options depend on the circle's members.
        super().__init__(timeout=900)
        self.add_item(ExclusionSelect(participant_id, options))


class ContactModal(discord.ui.Modal, title="Your contact info"):
    street = discord.ui.TextInput(label="Street and number", max_length=256)
    city_zip = discord.ui.TextInput(label="City and ZIP", max_length=128)
    phone = discord.ui.TextInput(label="Phone (optional)", required=False, max_length=32)
    digital = discord.ui.TextInput(
        label="Digital contact (optional)",
        required=False,
        max_length=256,
        placeholder="steam / telegram / email",
    )
    notes = discord.ui.TextInput(
        label="Notes (optional)",
        required=False,
        max_length=512,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, participant_id: int) -> None:
        super().__init__()
        self.participant_id = participant_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        street = self.street.value.strip()
        city_zip = self.city_zip.value.strip()
        if not street or not city_zip:
            await interaction.response.send_message(
                "Street and city can't be empty.", ephemeral=True
            )
            return

        payload = {
            "address": street,
            "city_zip": city_zip,
            "phone": (self.phone.value or "").strip() or None,
            "digital": (self.digital.value or "").strip() or None,
            "notes": (self.notes.value or "").strip() or None,
        }

        saved = False
        with get_session() as session:
            participant = session.get(Participant, self.participant_id)
            if participant is not None:
                save_contact(session, participant, payload)
                saved = True

        if not saved:
            await interaction.response.send_message(
                "This panel is no longer valid.", ephemeral=True
            )
            return

        await interaction.response.send_message("Saved.", ephemeral=True)
        await refresh_panel(interaction, self.participant_id)
        with get_session() as session:
            participant = session.get(Participant, self.participant_id)
            circle_id = participant.circle_id if participant is not None else None
        if circle_id is not None:
            # Whoever is giving to this participant needs the new address.
            await refresh_reveal_for(interaction.client, circle_id, self.participant_id)


class WishlistModal(discord.ui.Modal, title="Wishlist: add one item"):
    item_title = discord.ui.TextInput(label="What do you want?", max_length=512)
    url = discord.ui.TextInput(label="Link (optional)", required=False, max_length=2048)
    price = discord.ui.TextInput(
        label="Price in EUR (optional)",
        required=False,
        max_length=8,
        placeholder="25 or 25,50",
    )
    note = discord.ui.TextInput(
        label="Note (optional)",
        required=False,
        max_length=1024,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, participant_id: int) -> None:
        super().__init__()
        self.participant_id = participant_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        title = self.item_title.value.strip()
        if not title:
            await interaction.response.send_message(
                "The item needs a name.", ephemeral=True
            )
            return

        price_cents: int | None = None
        raw_price = (self.price.value or "").strip().replace(",", ".")
        if raw_price:
            try:
                price_cents = round(float(raw_price) * 100)
            except ValueError:
                price_cents = None
            if price_cents is None or price_cents <= 0:
                await interaction.response.send_message(
                    "Price must be a positive number, for example 25 or 25.50.",
                    ephemeral=True,
                )
                return

        added = False
        count = 0
        with get_session() as session:
            participant = session.get(Participant, self.participant_id)
            if participant is not None:
                count = wishlist_count(session, participant.id)
                if count < MAX_WISHLIST_ITEMS:
                    add_wishlist_item(
                        session,
                        participant,
                        title=title,
                        url=(self.url.value or "").strip() or None,
                        price=price_cents,
                        note=(self.note.value or "").strip() or None,
                    )
                    count += 1
                    added = True

        if not added:
            await interaction.response.send_message(
                "The wishlist is full (20 items) or this panel is no longer valid.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Added. Your wishlist has {count}/{MAX_WISHLIST_ITEMS} items.",
            ephemeral=True,
        )
        await refresh_panel(interaction, self.participant_id)


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        # Without this the panel buttons stop working after a restart.
        self.bot.add_view(PanelView())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Profile(bot))
