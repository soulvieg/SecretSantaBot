import discord
from discord.ext import commands

class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    santa = discord.app_commands.Group(name="santa", description="Secret Santa commands here")

    @santa.command(name="ping", description="Health check")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"Yoooooo!!! {round(self.bot.latency * 1000)} ms", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
