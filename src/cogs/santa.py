from datetime import datetime

import discord
from discord import Interaction, app_commands, embeds
from discord.ext import commands
from discord.sku import Entitlement


from db.engine import get_session
from db.rules import (
    AlreadyJoined,
    GroupNameTaken,
    GroupNotOpen,
    GroupNotFound,
    NotJoined,
    NotOwner,
    active_count,
    circle_from_card,
    close_signup,
    create_circle,
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
        if interaction.guild_id is None or not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message("Run this inside a text channel", ephemeral=True)
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
                embed = join_card(circle, 0, owner_id)
                circle_id = circle.id
        except GroupNameTaken:
            await interaction.response.send_message(f"You already have an event called **{name}** on this server", ephemeral=True)
            return

        message = await channel.send(embed=embed, view=JoinLeaveView())
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

        await interaction.response.send_message(
            "You left the event." if leaving else "You are in! 🎅", ephemeral=True
        )
        await interaction.message.edit(embed=embed)


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
        try:
            with get_session() as session:
                circle = find_circle(session, interaction.guild_id, name, interaction.channel_id)
                if circle is None:
                    raise GroupNotFound(name or "this channel")
                close_signup(session, circle, str(interaction.user.id))
                embed = join_card(circle, active_count(session, circle.id), owner_discord_id(session, circle))
                card_id = circle.card_msg_id
        except GroupNotFound:
            await interaction.response.send_message("No event found", ephemeral=True)
            return
        except NotOwner:
            await interaction.response.send_message("Only the organizer can close signups", ephemeral=True)
            return
        except GroupNotOpen:
            await interaction.response.send_message("Signups are already closed", ephemeral=True)
            return

        await interaction.response.send_message("Signups closed", ephemeral=True)
        channel = interaction.channel
        if card_id is not None and isinstance(channel, (discord.TextChannel, discord.Thread)):
            try:
                await channel.get_partial_message(card_id).edit(embed=embed, view=None)
            except discord.HTTPException:
                pass

    @santa.command(name="ping", description="Health check")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"Yoooooo!!! {round(self.bot.latency * 1000)} ms", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Santa(bot))
