import discord
from discord import app_commands
from discord.ext import commands


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
    pass




class Santa(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    santa = discord.app_commands.Group(name="santa", description="Secret Santa commands here")

    @santa.command(name="create", description="Create a new Secret Santa event")
    async def create(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Run this inside a server.", ephemeral=True)
            return
        await interaction.response.send_modal(CreateCircleModal())



    @santa.command(name="ping", description="Health check")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"Yoooooo!!! {round(self.bot.latency * 1000)} ms", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Santa(bot))
