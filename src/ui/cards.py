from datetime import datetime

import discord

from db.models import Circle
from times import discord_ts

STATUS = {
    "open": "Singup open",
    "info": "Collecting info",
    "drawn": "Names drawn",
    "closed": "Closed",
}


def _budget(circle: Circle) -> str:
    if circle.budget is None:
        return "No budget set"
    return f"{circle.budget / 100:.2f} {circle.currency}"



def _date(val: datetime | None, fallback: str) -> str:
    return discord_ts(val) if val is not None else fallback

def join_card(circle: Circle, participants: int, owner_id: str) -> discord.Embed:
    embed = discord.Embed(title=f"🎄 {circle.name}", color=discord.Color.green())
    embed.add_field(name="Budget", value=_budget(circle), inline=True)
    embed.add_field(name="Participants", value=str(participants), inline=True)
    embed.add_field(name="Signup deadline", value=_date(circle.signup_deadline, "Closed by organizer"), inline=False)
    embed.add_field(name="Exchange date", value=_date(circle.exchange_date, "Not set"), inline=False)
    embed.add_field(name="Status", value=STATUS.get(circle.status, circle.status), inline=False)
    embed.set_footer(text=f"Organizer: <@{owner_id}>")
    return embed


def status_card(circle: Circle, participants: int, owner_id: str, identity: str) -> discord.Embed:
    embed = join_card(circle=circle, participants=participants, owner_id=owner_id)
    embed.add_field(name="You are", value=identity, inline=False)
    return embed
