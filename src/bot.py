import discord
from discord.ext import commands
from config import Settings

class BotClient(commands.Bot):
    def __init__(self, settings: Settings, **kwargs):
        kwargs.setdefault("intents", discord.Intents.default())
        super().__init__(command_prefix=commands.when_mentioned,**kwargs)
        self.settings = settings


    async def setup_hook(self) -> None:
        await self.load_extension("cogs.general")

        # Setup for dev testing server
        if self.settings.dev:
            guild = discord.Object(id=self.settings.dev)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:
            synced = await self.tree.sync()
        print(f"Synced {len(synced)} commands")


    async def on_ready(self):
        print(f"Logged as {self.user}!")
