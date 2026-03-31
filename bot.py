from __future__ import annotations

"""
TFT Rank Tracker Discord Bot
-----------------------------
Tracks Teamfight Tactics ranks for players on a per-server leaderboard.

Setup:
1. Copy .env.example to .env and fill in your tokens.
2. pip install -r requirements.txt
3. python bot.py
"""

import asyncio
import logging
import time

import aiohttp
import discord
from discord.ext import commands, tasks

from config import DISCORD_TOKEN, RIOT_API_KEY, CACHE_TTL
from database import Database
from riot_client import RiotAPIError, RiotClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


class TFTBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        # message_content not needed — slash commands only
        super().__init__(command_prefix=None, intents=intents, help_command=None)

        self.db: Database = Database()
        self.riot: RiotClient | None = None
        self.cache_ttl: int = CACHE_TTL
        self._http_session: aiohttp.ClientSession | None = None

    async def setup_hook(self) -> None:
        # Initialise DB (creates tables, enables WAL)
        await self.db.init()
        log.info("Database initialised.")

        # Single shared aiohttp session for all Riot API calls
        self._http_session = aiohttp.ClientSession()
        self.riot = RiotClient(session=self._http_session, api_key=RIOT_API_KEY)

        # Load cogs
        for ext in ("cogs.registration", "cogs.leaderboard", "cogs.admin"):
            await self.load_extension(ext)
            log.info("Loaded extension: %s", ext)

        # Sync slash commands globally.
        # During development you may want to sync to a specific guild for instant propagation:
        #   await self.tree.sync(guild=discord.Object(id=YOUR_GUILD_ID))
        await self.tree.sync()
        log.info("Application commands synced.")

        # Start background loop
        self._background_loop.start()

    async def on_ready(self) -> None:
        assert self.user is not None
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching, name="TFT Ranks"
            )
        )

    async def on_guild_join(self, guild: discord.Guild) -> None:
        log.info("Joined guild: %s (ID: %s)", guild.name, guild.id)

    async def close(self) -> None:
        self._background_loop.cancel()
        if self._http_session:
            await self._http_session.close()
        await self.db.close()
        await super().close()

    # ------------------------------------------------------------------ #
    # Background loop — runs every 60 seconds                              #
    #   1. Refresh stale rank cache entries                                #
    #   2. Auto-post leaderboards for guilds whose interval has elapsed    #
    # ------------------------------------------------------------------ #

    @tasks.loop(seconds=60)
    async def _background_loop(self) -> None:
        now = int(time.time())

        # Step 1: Refresh stale cache entries
        cutoff = now - self.cache_ttl
        stale = await self.db.get_stale_cache_entries(cutoff)
        if stale:
            log.debug("Refreshing %d stale cache entries.", len(stale))
        for entry in stale:
            try:
                rank = await self.riot.refresh_rank(entry["puuid"], entry["region"])
                await self.db.upsert_rank_cache(
                    entry["puuid"],
                    entry["region"],
                    rank["tier"],
                    rank["division"],
                    rank["lp"],
                    rank["wins"],
                    rank["losses"],
                )
            except RiotAPIError as e:
                log.warning(
                    "Background refresh failed for puuid=%s region=%s: %s",
                    entry["puuid"],
                    entry["region"],
                    e,
                )
            # Small delay to stay well within Riot's rate limits
            await asyncio.sleep(0.5)

        # Step 2: Auto-post leaderboards
        due_guilds = await self.db.get_guilds_due_for_post(now)
        for settings in due_guilds:
            guild = self.get_guild(settings["guild_id"])
            if guild is None:
                continue
            channel = self.get_channel(settings["channel_id"])
            if not isinstance(channel, discord.TextChannel):
                continue

            leaderboard_cog = self.cogs.get("Leaderboard")
            if leaderboard_cog is None:
                continue

            try:
                msg_id = await leaderboard_cog.post_leaderboard_to_channel(
                    channel, guild, settings.get("last_message_id")
                )
                await self.db.upsert_guild_settings(
                    settings["guild_id"],
                    last_post_at=now,
                    last_message_id=msg_id,
                )
                log.info(
                    "Auto-posted leaderboard to guild=%s channel=%s",
                    guild.name,
                    channel.name,
                )
            except Exception as e:
                log.error(
                    "Failed to auto-post leaderboard for guild=%s: %s",
                    settings["guild_id"],
                    e,
                )

    @_background_loop.before_loop
    async def _before_background_loop(self) -> None:
        await self.wait_until_ready()


if __name__ == "__main__":
    bot = TFTBot()
    bot.run(DISCORD_TOKEN, log_handler=None)
