from datetime import timedelta

import discord
from discord.ext import commands, tasks

from cogs.profile import send_panels
from db.engine import get_session
from db.models import Circle, User
from db.rules import (
    GroupNotOpen,
    NotOwner,
    active_count,
    active_participants,
    close_signup,
    due_open_circles,
    owner_discord_id,
    purge_personal_data,
    stale_drawn_circles,
    utc_to_now,
)
from ui.cards import join_card

CLEANUP_GRACE = timedelta(days=14)


class Scheduler(commands.Cog):
    """Closes signups at the deadline and deletes personal data after the exchange."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.close_expired.start()
        self.purge_old.start()

    async def cog_unload(self) -> None:
        self.close_expired.cancel()
        self.purge_old.cancel()

    @tasks.loop(minutes=10)
    async def close_expired(self) -> None:
        with get_session() as session:
            circle_ids = due_open_circles(session, utc_to_now())
        for circle_id in circle_ids:
            await self._close_circle(circle_id)

    @tasks.loop(hours=6)
    async def purge_old(self) -> None:
        cutoff = utc_to_now() - CLEANUP_GRACE
        with get_session() as session:
            circle_ids = stale_drawn_circles(session, cutoff)
            for circle_id in circle_ids:
                circle = session.get(Circle, circle_id)
                if circle is None:
                    continue
                purge_personal_data(session, circle.id)
                circle.status = "closed"

    async def _close_circle(self, circle_id: int) -> None:
        """Same work as /santa close_signup, but triggered by the deadline."""
        embed: discord.Embed | None = None
        card_id: int | None = None
        card_channel_id: int | None = None
        owner = ""
        name = ""
        targets: list[tuple[int, str]] = []
        try:
            with get_session() as session:
                circle = session.get(Circle, circle_id)
                if circle is None or circle.status != "open":
                    return
                owner = owner_discord_id(session, circle)
                name = circle.name
                close_signup(session, circle, owner)
                embed = join_card(circle, active_count(session, circle.id), owner)
                card_id = circle.card_msg_id
                card_channel_id = circle.announce_channel_id
                for participant in active_participants(session, circle.id):
                    user = session.get(User, participant.user_id)
                    if user is not None and user.discord_id:
                        targets.append((participant.id, user.discord_id))
        except (NotOwner, GroupNotOpen):
            return

        if card_id is not None and embed is not None:
            channel = self.bot.get_channel(card_channel_id) if card_channel_id else None
            if isinstance(channel, (discord.TextChannel, discord.Thread)):
                try:
                    await channel.get_partial_message(card_id).edit(embed=embed, view=None)
                except discord.HTTPException:
                    pass

        sent, failed = await send_panels(self.bot, circle_id, targets)
        if not owner:
            return
        report = (
            f"Signups for **{name}** closed on the deadline. "
            f"Setup panels sent to {sent}/{len(targets)} participants."
        )
        if failed:
            report += "\nDM closed for: " + ", ".join(
                f"<@{discord_id}>" for discord_id in failed
            )
        try:
            user = await self.bot.fetch_user(int(owner))
            await user.send(report)
        except (ValueError, discord.HTTPException):
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Scheduler(bot))
