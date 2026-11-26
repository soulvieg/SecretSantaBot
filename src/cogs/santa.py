from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from cogs.gift import refresh_reveal_for, run_draw, send_reveal
from cogs.profile import send_panels
from db.engine import get_session
from db.models import Circle, User
from db.rules import (
    AlreadyClosed,
    AlreadyJoined,
    GroupNameTaken,
    GroupNotFound,
    GroupNotOpen,
    NotJoined,
    NotOwner,
    OwnerCannotLeave,
    active_count,
    active_participants,
    add_participant_after_draw,
    assignment_for,
    circle_from_card,
    close_circle,
    close_signup,
    create_circle,
    delete_circle,
    find_circle,
    join_circle,
    leave_circle,
    owner_discord_id,
    role_of,
    set_card,
)
from times import optional_parse
from ui.cards import join_card, status_card


class CreateCircleModal(discord.ui.Modal, title="New secret santa event"):
    name=discord.ui.TextInput(label="Event name", placeholder=f"Xmas {datetime.now().year}", min_length=4, max_length=64)
    budget = discord.ui.TextInput(label="Budget (optional)", required=False, max_length=6)
    deadline = discord.ui.TextInput(label="Signup deadline (optional)", required=False, max_length=16)
    exchange = discord.ui.TextInput(label="Exchange date (optional)", required=False, max_length=16)
    avoid_repeat = discord.ui.TextInput(label="No repeat gifts? (yes/no)", placeholder="no", required=False, max_length=3)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if (
            interaction.guild_id is None
            or interaction.guild is None
            or not isinstance(channel, discord.abc.GuildChannel)
            or not isinstance(channel, discord.abc.Messageable)
        ):
            await interaction.response.send_message("Run this inside a text channel", ephemeral=True)
            return

        required = [
            ("view_channel", "View Channel"),
            ("send_messages", "Send Messages"),
            ("embed_links", "Embed Links"),
        ]
        if isinstance(channel, discord.Thread):
            required.append(("send_messages_in_threads", "Send Messages in Threads"))
        member = interaction.guild.me
        if member is not None:
            permissions = channel.permissions_for(member)
            missing = [label for attr, label in required if not getattr(permissions, attr)]
            if missing:
                await interaction.response.send_message(
                    "I can't post the signup card in this channel. Missing: "
                    + ", ".join(missing),
                    ephemeral=True,
                )
                return

        budget = None
        if self.budget.value.strip():
            try:
                budget = int(self.budget.value) * 100
            except ValueError:
                await interaction.response.send_message("Budget must be a whole number of money", ephemeral=True)
                return
            if budget <= 0:
                await interaction.response.send_message("Budget must be positive", ephemeral=True)
                return

        try:
            deadline = optional_parse(self.deadline.value)
            exchange = optional_parse(self.exchange.value)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        name = self.name.value.strip()
        owner_id = str(interaction.user.id)

        try:
            with get_session() as session:
                circle = create_circle(session, name=name, owner_id=owner_id, discord_server_id=interaction.guild_id, budget=budget, signup_deadline=deadline, exchange_date=exchange, avoid_repeat=self.avoid_repeat.value.strip().lower() in {"yes", "y", "si", "sì", "true"})
                embed = join_card(circle, active_count(session, circle.id), owner_id)
                circle_id = circle.id
        except GroupNameTaken:
            await interaction.response.send_message(f"You already have an event called **{name}** on this server", ephemeral=True)
            return

        try:
            message = await channel.send(embed=embed, view=JoinLeaveView())
        except discord.Forbidden:
            with get_session() as session:
                delete_circle(session, circle_id)
            await interaction.response.send_message(
                "Discord denied the signup card: check my permissions in this channel "
                "(View Channel, Send Messages, Embed Links).",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            with get_session() as session:
                delete_circle(session, circle_id)
            await interaction.response.send_message(
                "Discord rejected the signup card. Try again in a moment.",
                ephemeral=True,
            )
            return

        with get_session() as session:
            set_card(session, circle_id, channel.id, message.id)

        await interaction.response.send_message(f"Created **{name}**.", ephemeral=True)


class JoinLeaveView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success, custom_id="santa:join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._join_or_leave(interaction, leaving=False)

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.secondary, custom_id="santa:leave")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._join_or_leave(interaction, leaving=True)

    async def _join_or_leave(self, interaction: discord.Interaction, *, leaving: bool) -> None:
        if interaction.message is None:
            return
        try:
            with get_session() as session:
                circle = circle_from_card(session, interaction.message.id)
                if circle is None:
                    raise GroupNotFound(interaction.message.id)
                if leaving:
                    leave_circle(session, circle, str(interaction.user.id))
                else:
                    join_circle(session, circle, str(interaction.user.id))
                embed = join_card(circle, active_count(session, circle.id), owner_discord_id(session, circle))
        except GroupNotFound:
            await interaction.response.send_message("This event is over or was deleted.", ephemeral=True)
            return
        except GroupNotOpen:
            await interaction.response.send_message("Signups are closed for this event.", ephemeral=True)
            return
        except AlreadyJoined:
            await interaction.response.send_message("You are already signed up.", ephemeral=True)
            return
        except NotJoined:
            await interaction.response.send_message("You are not signed up for this event.", ephemeral=True)
            return
        except OwnerCannotLeave:
            await interaction.response.send_message("Organizers can't leave their own event.", ephemeral=True)
            return

        await interaction.response.send_message(
            "You left the event." if leaving else "You are in! 🎅", ephemeral=True
        )
        try:
            await interaction.message.edit(embed=embed)
        except discord.HTTPException:
            pass


class ConfirmCloseView(discord.ui.View):
    """Destructive action, so it needs an explicit second click."""

    def __init__(self, circle_id: int, name: str) -> None:
        super().__init__(timeout=120)
        self.circle_id = circle_id
        self.name = name

    @discord.ui.button(label="Delete data and close", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        state = "ok"
        card_id: int | None = None
        card_channel_id: int | None = None
        card_embed: discord.Embed | None = None
        with get_session() as session:
            circle = session.get(Circle, self.circle_id)
            if circle is None:
                state = "gone"
            else:
                try:
                    close_circle(session, circle, str(interaction.user.id))
                except NotOwner:
                    state = "not_owner"
                except AlreadyClosed:
                    state = "closed"
                else:
                    card_id = circle.card_msg_id
                    card_channel_id = circle.announce_channel_id
                    card_embed = join_card(
                        circle,
                        active_count(session, circle.id),
                        owner_discord_id(session, circle),
                    )

        self.stop()
        if state == "gone":
            await interaction.response.edit_message(
                content="This event no longer exists.", embed=None, view=None
            )
            return
        if state == "not_owner":
            await interaction.response.edit_message(
                content="Only the organizer can close the event.", embed=None, view=None
            )
            return
        if state == "closed":
            await interaction.response.edit_message(
                content="This event was already closed.", embed=None, view=None
            )
            return
        await interaction.response.edit_message(
            content=(
                f"**{self.name}** is closed. Addresses, wishlists, exclusions "
                "and shipments are deleted."
            ),
            embed=None,
            view=None,
        )
        channel = interaction.client.get_channel(card_channel_id) if card_channel_id else None
        if card_embed is not None and card_id is not None and isinstance(channel, (discord.TextChannel, discord.Thread)):
            try:
                await channel.get_partial_message(card_id).edit(embed=card_embed, view=None)
            except discord.HTTPException:
                pass


class Santa(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(JoinLeaveView())

    santa = discord.app_commands.Group(name="santa", description="Secret Santa commands here")

    @santa.command(name="create", description="Create a new Secret Santa event")
    async def create(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Run this inside a server.", ephemeral=True)
            return
        await interaction.response.send_modal(CreateCircleModal())

    @santa.command(name="status", description="Show the status of the event")
    @app_commands.describe(name="Event name; defaults to the event in this channel")
    async def status(self, interaction: discord.Interaction, name: str | None = None) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Run this command inside a server!", ephemeral=True)
            return
        with get_session() as session:
            circle = find_circle(session, interaction.guild_id, name, interaction.channel_id)
            if circle is None:
                await interaction.response.send_message("No event found", ephemeral=True)
                return
            embed = status_card(circle, active_count(session, circle.id), owner_discord_id(session, circle), role_of(session, circle, str(interaction.user.id)))
        await interaction.response.send_message(embed=embed, ephemeral=True)


    @santa.command(name="close_signup", description="Close signups and start collecting info")
    @app_commands.describe(name="Event name; default to the event in this channel")
    async def close_signup(self, interaction: discord.Interaction, name: str | None = None) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Run this inside a server!", ephemeral=True)
            return
        # Sending the panels takes longer than the 3 second interaction window.
        await interaction.response.defer(ephemeral=True)

        embed: discord.Embed | None = None
        card_id: int | None = None
        circle_id = 0
        targets: list[tuple[int, str]] = []
        try:
            with get_session() as session:
                circle = find_circle(session, interaction.guild_id, name, interaction.channel_id)
                if circle is None:
                    raise GroupNotFound(name or "this channel")
                close_signup(session, circle, str(interaction.user.id))
                embed = join_card(circle, active_count(session, circle.id), owner_discord_id(session, circle))
                card_id = circle.card_msg_id
                circle_id = circle.id
                for participant in active_participants(session, circle.id):
                    user = session.get(User, participant.user_id)
                    if user is not None and user.discord_id:
                        targets.append((participant.id, user.discord_id))
        except GroupNotFound:
            await interaction.followup.send("No event found", ephemeral=True)
            return
        except NotOwner:
            await interaction.followup.send("Only the organizer can close signups", ephemeral=True)
            return
        except GroupNotOpen:
            await interaction.followup.send("Signups are already closed", ephemeral=True)
            return

        channel = interaction.channel
        if card_id is not None and embed is not None and isinstance(channel, (discord.TextChannel, discord.Thread)):
            try:
                await channel.get_partial_message(card_id).edit(embed=embed, view=None)
            except discord.HTTPException:
                pass

        sent, failed = await send_panels(self.bot, circle_id, targets)
        report = f"Signups closed. Panels sent to {sent}/{len(targets)} participants."
        if failed:
            report += "\nDM closed for: " + ", ".join(f"<@{discord_id}>" for discord_id in failed)
        await interaction.followup.send(report, ephemeral=True)

    @santa.command(name="close", description="Close the event and delete all personal data")
    @app_commands.describe(name="Event name; defaults to the event in this channel")
    async def close(self, interaction: discord.Interaction, name: str | None = None) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Run this inside a server!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        found = False
        circle_id = 0
        circle_name = ""
        status = ""
        with get_session() as session:
            circle = find_circle(session, interaction.guild_id, name, interaction.channel_id)
            if circle is None:
                found = False
            elif role_of(session, circle, str(interaction.user.id)) != "organizer":
                status = "not_owner"
                found = True
            else:
                found = True
                circle_id = circle.id
                circle_name = circle.name
                status = circle.status

        if not found:
            await interaction.followup.send("No event found", ephemeral=True)
            return
        if status == "not_owner":
            await interaction.followup.send("Only the organizer can close the event", ephemeral=True)
            return
        if status == "closed":
            await interaction.followup.send("This event is already closed", ephemeral=True)
            return

        await interaction.followup.send(
            f"Close **{circle_name}**? Addresses, wishlists, exclusions and shipments "
            "will be deleted. Names and assignments stay, without personal data.",
            view=ConfirmCloseView(circle_id, circle_name),
            ephemeral=True,
        )

    @santa.command(name="add", description="Add a participant after the draw")
    @app_commands.describe(
        member="Who to add", name="Event name; defaults to the event in this channel"
    )
    async def add(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        name: str | None = None,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Run this inside a server!", ephemeral=True)
            return
        # Sending the panel and the reveal takes a few seconds.
        await interaction.response.defer(ephemeral=True)

        outcome = "ok"
        circle_id = 0
        participant_id = 0
        with get_session() as session:
            circle = find_circle(session, interaction.guild_id, name, interaction.channel_id)
            if circle is None:
                outcome = "not_found"
            elif role_of(session, circle, str(interaction.user.id)) != "organizer":
                outcome = "not_owner"
            else:
                try:
                    participant_id, _ = add_participant_after_draw(
                        session, circle, str(member.id)
                    )
                except GroupNotOpen:
                    outcome = "not_drawn"
                except AlreadyJoined:
                    outcome = "already"
                except GroupNotFound:
                    outcome = "no_assignments"
                else:
                    circle_id = circle.id

        if outcome != "ok":
            messages = {
                "not_found": "No event found",
                "not_owner": "Only the organizer can add people",
                "not_drawn": "Names are not drawn yet: ask them to use the Join button",
                "already": f"{member.display_name} is already in",
                "no_assignments": "This event has no assignments to extend",
            }
            await interaction.followup.send(messages[outcome], ephemeral=True)
            return

        sent, _ = await send_panels(
            self.bot, circle_id, [(participant_id, str(member.id))]
        )
        with get_session() as session:
            assignment = assignment_for(session, circle_id, participant_id)
            assignment_id = assignment.id if assignment is not None else None
        reveal_ok = True
        if assignment_id is not None:
            reveal_ok, _ = await send_reveal(self.bot, assignment_id)
        await refresh_reveal_for(self.bot, circle_id, participant_id)

        report = f"{member.mention} is in."
        if sent == 0:
            report += "\nI couldn't DM them the setup panel: their DMs are closed."
        if not reveal_ok:
            report += "\nI couldn't DM them their giftee either."
        await interaction.followup.send(report, ephemeral=True)

    @santa.command(name="ping", description="Health check")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"Yoooooo!!! {round(self.bot.latency * 1000)} ms", ephemeral=True
        )

    @santa.command(name="draw", description="Draw the names now, if everyone is ready")
    @app_commands.describe(name="Event name; defaults to the event in this channel")
    async def draw(self, interaction: discord.Interaction, name: str | None = None) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Run this inside a server!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        outcome = "ok"
        circle_id = 0
        missing: list[str] = []
        with get_session() as session:
            circle = find_circle(session, interaction.guild_id, name, interaction.channel_id)
            if circle is None:
                outcome = "not_found"
            elif role_of(session, circle, str(interaction.user.id)) != "organizer":
                outcome = "not_owner"
            elif circle.status == "open":
                outcome = "still_open"
            elif circle.status != "collecting":
                outcome = "not_collecting"
            else:
                circle_id = circle.id
                for participant in active_participants(session, circle.id):
                    if participant.ready:
                        continue
                    user = session.get(User, participant.user_id)
                    if user is not None and user.discord_id:
                        missing.append(user.discord_id)

        if outcome != "ok":
            messages = {
                "not_found": "No event found",
                "not_owner": "Only the organizer can draw",
                "still_open": "Close signups first with /santa close_signup",
                "not_collecting": "Names were already drawn",
            }
            await interaction.followup.send(messages[outcome], ephemeral=True)
            return

        if missing:
            await interaction.followup.send(
                "These participants are not ready yet: "
                + ", ".join(f"<@{discord_id}>" for discord_id in missing),
                ephemeral=True,
            )
            return

        status, failed = await run_draw(interaction.client, circle_id)
        if status == "drawn":
            report = "Names drawn. Reveal DMs sent."
            if failed:
                report += "\nI couldn't DM: " + ", ".join(
                    f"<@{discord_id}>" for discord_id in failed
                )
            await interaction.followup.send(report, ephemeral=True)
        elif status == "impossible":
            await interaction.followup.send(
                "The exclusions leave no valid draw. Ask someone to relax theirs.",
                ephemeral=True,
            )
        elif status == "already":
            await interaction.followup.send("Names were already drawn.", ephemeral=True)
        else:
            await interaction.followup.send("No event found", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Santa(bot))
