from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from config import (
    PLAYERS_PER_PAGE,
    AUTO_POST_PLAYERS_PER_PAGE,
    MEDALS,
    TIER_COLORS,
    format_rank,
    rank_score,
)
from riot_client import RiotAPIError

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Paginated view                                                        #
# ------------------------------------------------------------------ #

class PaginatedLeaderboard(discord.ui.View):
    """Paginated leaderboard view with Previous / Next buttons."""

    def __init__(self, pages: list[discord.Embed], *, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.current = 0
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.prev_btn.disabled = self.current == 0  # type: ignore[union-attr]
        self.next_btn.disabled = self.current >= len(self.pages) - 1  # type: ignore[union-attr]

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.current -= 1
        self._sync_buttons()
        await interaction.response.edit_message(
            embed=self.pages[self.current], view=self
        )

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.current += 1
        self._sync_buttons()
        await interaction.response.edit_message(
            embed=self.pages[self.current], view=self
        )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]


# ------------------------------------------------------------------ #
# Embed builder helpers                                                 #
# ------------------------------------------------------------------ #

def _linked_suffix(
    linked_accounts: list[dict[str, Any]],
    rank_cache: Dict[Tuple[str, str], dict[str, Any]],
) -> str:
    """Build a compact suffix showing linked region accounts, e.g. *(KR: Name#KR1 💙 Diamond I 50 LP)*"""
    parts: list[str] = []
    for acct in linked_accounts:
        cache = rank_cache.get((acct["puuid"], acct["region"]))
        rank_str = (
            format_rank(cache["tier"], cache["division"], cache["lp"])
            if cache
            else "Unranked"
        )
        parts.append(f"**{acct['region']}:** {acct['game_name']}#{acct['tag_line']} — {rank_str}")
    return "\n".join(f"↳ {p}" for p in parts) if parts else ""


def build_leaderboard_pages(
    rows: list[dict[str, Any]],
    linked_map: dict[int, list[dict[str, Any]]],
    rank_cache: dict[tuple[str, str], dict[str, Any]],
    guild_name: str,
    discord_members: dict[int, discord.Member],
    players_per_page: int = PLAYERS_PER_PAGE,
) -> list[discord.Embed]:
    """
    Build a list of paginated Embed objects from sorted player rows.

    Args:
        rows: Sorted list of registration dicts (highest rank first).
        linked_map: discord_id → list of linked account dicts.
        rank_cache: (puuid, region) → rank_cache dict.
        guild_name: Display name for the embed title.
        discord_members: discord_id → discord.Member for display names.
    """
    if not rows:
        empty = discord.Embed(
            title=f"☀️ Bootcamp Leaderboard",
            description="No players registered yet.\nUse `/register` to join the leaderboard!",
            color=0x2B2D31,
        )
        empty.set_footer(text="TFT Rank Tracker")
        return [empty]

    pages: list[discord.Embed] = []
    total_pages = (len(rows) + players_per_page - 1) // players_per_page
    # Unix timestamp used for Discord's native <t:N:R> localized rendering
    updated_unix = int(datetime.now(timezone.utc).timestamp())
    # updated_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    # updated_ts = datetime.now(timezone.utc)

    # Accent color from the top player's tier
    top_cache = rank_cache.get((rows[0]["puuid"], "NA"))
    # accent = TIER_COLORS.get((top_cache or {}).get("tier") or "UNRANKED", 0x2B2D31)
    accent = TIER_COLORS.get("KATE", 0x2B2D31)

    for page_idx in range(total_pages):
        chunk = rows[page_idx * players_per_page : (page_idx + 1) * players_per_page]
        lines: list[str] = []

        for offset, reg in enumerate(chunk):
            position = page_idx * players_per_page + offset + 1
            medal = MEDALS.get(position, f"`#{position:02d}`")

            cache = rank_cache.get((reg["puuid"], "NA"))
            rank_str = (
                format_rank(cache["tier"], cache["division"], cache["lp"])
                if cache
                else "Unranked"
            )

            member = discord_members.get(reg["discord_id"])
            display_name = member.display_name if member else f"<@{reg['discord_id']}>"

            line = (
                f"{medal} **{reg['game_name']}#{reg['tag_line']}** — {rank_str}\n"
                f"　　{display_name}"
            )

            linked = linked_map.get(reg["discord_id"], [])
            suffix = _linked_suffix(linked, rank_cache)
            if suffix:
                line += f"\n{suffix}"

            lines.append(line)

        # <t:N:R> renders as "2 minutes ago" in each viewer's local timezone.
        # <t:N:f> renders as "March 31, 2026 at 10:00 AM" localized.
        # Discord only localizes timestamps in description/fields, not footer text.
        description = "\n\n".join(lines) + f"\n\n-# Updated <t:{updated_unix}:R>"

        embed = discord.Embed(
            title=f"☀️ Bootcamp Leaderboard",
            description=description,
            color=accent,
        )
        embed.set_footer(
            text=f"Page {page_idx + 1}/{total_pages} · {len(rows)} players"
        )
        # embed.set_image(url="https://greekgamingacademy.gr/wp-content/uploads/2023/10/Every-TFT-Set.jpg")
        # embed.set_image(url="https://cdn.discordapp.com/attachments/1259591457040502788/1488455221368590487/image.png?ex=69ccd772&is=69cb85f2&hm=f095c908f9d7e7afc671ec880abdcff93c7f89179376bebac782e238fca6d55b&")
        # embed.set_image(url="https://cdn.discordapp.com/attachments/1259591457040502788/1488458385253728276/image.png?ex=69ccda65&is=69cb88e5&hm=53d214cdd4ad1360c390287edbc2826aca5fae39d7109ed4a2f7c6d0cd69ccbd&")
        embed.set_image(url="https://cdn.discordapp.com/attachments/1259591457040502788/1488459492730474618/image.png?ex=69ccdb6d&is=69cb89ed&hm=2e9ffb4bb0e511c8fce507e822b6a44a2f6c68561175bfe7154ad6a349427c56&")
        # embed.set_thumbnail(url="https://yt3.googleusercontent.com/Nw2kKyqls4sc8kTQWwfIEBAl_Igg-94HgBwdDGDPcK5OuH9vN7svRyHe2Dv6ojY17AJSnGLfTw=s900-c-k-c0x00ffffff-no-rj")
        # embed.set_thumbnail(url="https://media.discordapp.net/attachments/1259591457040502788/1488457138803179670/image.png?ex=69ccd93c&is=69cb87bc&hm=10caadab2daa23c72d4c995c68e292a2eaa34648e8a9b38e8902efcaae6f1188&=&format=webp&quality=lossless&width=1334&height=1330")
        # embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1259591457040502788/1488456636094877716/hi_112.png?ex=69ccd8c4&is=69cb8744&hm=409fa379b0d321bafb871dbf0ff3c56d57d855d44a9c8324d63a8c8e8d4cb701&")
        embed.set_thumbnail(url="https://media.discordapp.net/attachments/1259591457040502788/1488461433099386980/Your_paragraph_text_12.png?ex=69ccdd3b&is=69cb8bbb&hm=6b6b56d571618694816ce6ac5e651f70fc4c8653afcc34bd4522209e45578d00&=&format=webp&quality=lossless")
        pages.append(embed)

    return pages


# ------------------------------------------------------------------ #
# Cog                                                                   #
# ------------------------------------------------------------------ #

class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _build_guild_pages(
        self, guild: discord.Guild, players_per_page: int = PLAYERS_PER_PAGE
    ) -> list[discord.Embed]:
        """Fetch all data for a guild, refresh stale entries, and build embed pages."""
        registrations = await self.bot.db.get_all_registrations(guild.id)
        if not registrations:
            return [
                discord.Embed(
                    title=f"☀️ Bootcamp Leaderboard",
                    description="No players registered yet. Use `/register` to join!",
                    color=0x2B2D31,
                )
            ]

        # Collect all (puuid, region) pairs we need
        needed: list[tuple[str, str]] = []  # (puuid, region)
        for reg in registrations:
            needed.append((reg["puuid"], "NA"))

        linked_map: dict[int, list[dict[str, Any]]] = {}
        for reg in registrations:
            linked = await self.bot.db.get_linked_accounts(guild.id, reg["discord_id"])
            if linked:
                linked_map[reg["discord_id"]] = linked
                for acct in linked:
                    needed.append((acct["puuid"], acct["region"]))

        # Refresh any stale cache entries for this specific set of players
        now = int(time.time())
        rank_cache: dict[tuple[str, str], dict[str, Any]] = {}
        for puuid, region in needed:
            cached = await self.bot.db.get_rank_cache(puuid, region)
            if cached and (now - cached["updated_at"]) < self.bot.cache_ttl:
                rank_cache[(puuid, region)] = cached
            else:
                try:
                    rank = await self.bot.riot.refresh_rank(puuid, region)
                    await self.bot.db.upsert_rank_cache(
                        puuid, region,
                        rank["tier"], rank["division"],
                        rank["lp"], rank["wins"], rank["losses"],
                    )
                    cached = await self.bot.db.get_rank_cache(puuid, region)
                    rank_cache[(puuid, region)] = cached or {}
                except RiotAPIError as e:
                    log.warning("Failed to refresh %s/%s: %s", puuid, region, e)
                    rank_cache[(puuid, region)] = cached or {}

        # Sort registrations by NA rank score
        def _score(reg: dict[str, Any]) -> int:
            c = rank_cache.get((reg["puuid"], "NA"), {})
            return rank_score(c.get("tier"), c.get("division"), c.get("lp", 0))

        sorted_regs = sorted(registrations, key=_score, reverse=True)

        # Build member display name map
        member_map: dict[int, discord.Member] = {
            m.id: m for m in guild.members
        }

        return build_leaderboard_pages(
            sorted_regs, linked_map, rank_cache, guild.name, member_map, players_per_page
        )

    # ------------------------------------------------------------------ #
    # /leaderboard                                                          #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="leaderboard",
        description="Show the TFT rank leaderboard for this server.",
    )
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        pages = await self._build_guild_pages(interaction.guild)

        if len(pages) == 1:
            await interaction.followup.send(embed=pages[0], ephemeral=True)
        else:
            view = PaginatedLeaderboard(pages)
            await interaction.followup.send(embed=pages[0], view=view, ephemeral=True)

    # ------------------------------------------------------------------ #
    # /rank                                                                 #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="rank",
        description="Check a specific player's TFT rank.",
    )
    @app_commands.describe(
        member="The Discord member to look up (defaults to yourself)"
    )
    async def rank(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ) -> None:
        await interaction.response.defer()

        target = member or interaction.user
        reg = await self.bot.db.get_registration(interaction.guild_id, target.id)
        if not reg:
            name = target.display_name
            await interaction.followup.send(
                f"**{name}** is not registered on this server's leaderboard. "
                "They can use `/register` to join.",
                ephemeral=True,
            )
            return

        # Refresh NA rank if stale
        now = int(time.time())
        na_cache = await self.bot.db.get_rank_cache(reg["puuid"], "NA")
        if not na_cache or (now - na_cache["updated_at"]) >= self.bot.cache_ttl:
            try:
                rank_data = await self.bot.riot.refresh_rank(reg["puuid"], "NA")
                await self.bot.db.upsert_rank_cache(
                    reg["puuid"], "NA",
                    rank_data["tier"], rank_data["division"],
                    rank_data["lp"], rank_data["wins"], rank_data["losses"],
                )
                na_cache = await self.bot.db.get_rank_cache(reg["puuid"], "NA")
            except RiotAPIError as e:
                log.warning("Rank refresh failed for %s: %s", reg["game_name"], e)

        tier = (na_cache or {}).get("tier")
        division = (na_cache or {}).get("division")
        lp = (na_cache or {}).get("lp", 0)
        wins = (na_cache or {}).get("wins", 0)
        losses = (na_cache or {}).get("losses", 0)

        rank_str = format_rank(tier, division, lp)
        color = TIER_COLORS.get(tier or "UNRANKED", 0x2B2D31)

        embed = discord.Embed(
            title=f"{reg['game_name']}#{reg['tag_line']}",
            color=color,
        )
        embed.set_author(
            name=target.display_name,
            icon_url=target.display_avatar.url,
        )
        embed.add_field(name="NA Rank", value=rank_str, inline=True)

        if tier:
            total = (wins or 0) + (losses or 0)
            if total:
                wr = round(wins / total * 100, 1)
                embed.add_field(
                    name="Win Rate",
                    value=f"{wr}% ({wins}W / {losses}L)",
                    inline=True,
                )

        # Linked accounts
        linked = await self.bot.db.get_linked_accounts(interaction.guild_id, target.id)
        for acct in linked:
            cache = await self.bot.db.get_rank_cache(acct["puuid"], acct["region"])
            # Refresh if stale
            if not cache or (now - cache["updated_at"]) >= self.bot.cache_ttl:
                try:
                    r = await self.bot.riot.refresh_rank(acct["puuid"], acct["region"])
                    await self.bot.db.upsert_rank_cache(
                        acct["puuid"], acct["region"],
                        r["tier"], r["division"], r["lp"], r["wins"], r["losses"],
                    )
                    cache = await self.bot.db.get_rank_cache(acct["puuid"], acct["region"])
                except RiotAPIError:
                    pass

            linked_rank = (
                format_rank(cache["tier"], cache["division"], cache["lp"])
                if cache
                else "Unranked"
            )
            embed.add_field(
                name=f"🌐 {acct['region']} (Linked)",
                value=f"{acct['game_name']}#{acct['tag_line']}\n{linked_rank}",
                inline=True,
            )

        if na_cache:
            ts = datetime.fromtimestamp(na_cache["updated_at"], tz=timezone.utc)
            embed.set_footer(
                text=f"Last updated: {ts.strftime('%Y-%m-%d %H:%M UTC')}"
            )
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------ #
    # Auto-post helper (called by bot's background loop)                    #
    # ------------------------------------------------------------------ #

    async def post_leaderboard_to_channel(
        self, channel: discord.TextChannel, guild: discord.Guild, last_message_id: int | None
    ) -> int | None:
        """
        Post or edit the leaderboard in the given channel.
        Returns the message id of the posted/edited message.
        """
        pages = await self._build_guild_pages(guild, players_per_page=AUTO_POST_PLAYERS_PER_PAGE)
        embed = pages[0]
        # Add page count hint to footer for auto-posts
        if len(pages) > 1:
            old_footer = embed.footer.text or ""
            embed.set_footer(
                text=f"{old_footer} · Use /leaderboard for full pagination"
            )

        if last_message_id:
            try:
                msg = await channel.fetch_message(last_message_id)
                await msg.edit(embed=embed, view=None)
                return msg.id
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass  # Fall through to sending a new message

        msg = await channel.send(embed=embed)
        return msg.id


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Leaderboard(bot))
