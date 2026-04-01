from __future__ import annotations

import logging
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from riot_client import RiotAPIError

log = logging.getLogger(__name__)


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------ #
    # /set-channel                                                          #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="set-channel",
        description="Set the channel where the leaderboard will be auto-posted.",
    )
    @app_commands.describe(
        channel="The channel to post to (defaults to the current channel)"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def set_channel(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.abc.GuildChannel] = None,
    ) -> None:
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message(
                "Please specify a text channel.", ephemeral=True
            )
            return

        await self.bot.db.upsert_guild_settings(
            interaction.guild_id, channel_id=target.id
        )
        await interaction.response.send_message(
            f"✅ Auto-post channel set to {target.mention}.", ephemeral=True
        )

    # ------------------------------------------------------------------ #
    # /set-interval                                                         #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="set-interval",
        description="Set how often (in minutes) the leaderboard is automatically posted.",
    )
    @app_commands.describe(minutes="Posting interval in minutes (minimum: 10)")
    @app_commands.default_permissions(manage_guild=True)
    async def set_interval(
        self, interaction: discord.Interaction, minutes: int
    ) -> None:
        if minutes < 10:
            await interaction.response.send_message(
                "Minimum interval is 10 minutes.", ephemeral=True
            )
            return
        if minutes > 1440:
            await interaction.response.send_message(
                "Maximum interval is 1440 minutes (24 hours).", ephemeral=True
            )
            return

        seconds = minutes * 60
        await self.bot.db.upsert_guild_settings(
            interaction.guild_id, post_interval=seconds
        )
        await interaction.response.send_message(
            f"✅ Auto-post interval set to every **{minutes} minutes**.", ephemeral=True
        )

    # ------------------------------------------------------------------ #
    # /disable-autopost                                                     #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="disable-autopost",
        description="Disable automatic leaderboard posting for this server.",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def disable_autopost(self, interaction: discord.Interaction) -> None:
        await self.bot.db.upsert_guild_settings(
            interaction.guild_id, channel_id=None, last_message_id=None
        )
        await interaction.response.send_message(
            "✅ Auto-posting disabled. Use `/set-channel` to re-enable.", ephemeral=True
        )

    # ------------------------------------------------------------------ #
    # /force-post                                                           #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="force-post",
        description="Immediately post the leaderboard to the configured channel.",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def force_post(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        settings = await self.bot.db.get_guild_settings(interaction.guild_id)
        if not settings or not settings.get("channel_id"):
            await interaction.followup.send(
                "No auto-post channel configured. Use `/set-channel` first.",
                ephemeral=True,
            )
            return

        channel = self.bot.get_channel(settings["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send(
                "Configured channel not found or inaccessible.", ephemeral=True
            )
            return

        leaderboard_cog = self.bot.cogs.get("Leaderboard")
        if leaderboard_cog is None:
            await interaction.followup.send("Leaderboard cog not loaded.", ephemeral=True)
            return

        msg_id = await leaderboard_cog.post_leaderboard_to_channel(
            channel, settings.get("last_message_id")
        )
        await self.bot.db.upsert_guild_settings(
            interaction.guild_id,
            last_post_at=int(time.time()),
            last_message_id=msg_id,
        )
        await interaction.followup.send(
            f"✅ Leaderboard posted to {channel.mention}.", ephemeral=True
        )

    # ------------------------------------------------------------------ #
    # /force-refresh                                                        #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="force-refresh",
        description="Force-refresh all player ranks from Riot API.",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def force_refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        await self.bot.db.invalidate_all_cache()

        registrations = await self.bot.db.get_all_registrations()
        if not registrations:
            await interaction.followup.send(
                "No players registered on the leaderboard.", ephemeral=True
            )
            return

        await interaction.followup.send(
            f"⏳ Refreshing ranks for **{len(registrations)}** player(s)...",
            ephemeral=True,
        )

        success = 0
        failed = 0
        for reg in registrations:
            try:
                rank = await self.bot.riot.refresh_rank(reg["puuid"], "NA")
                await self.bot.db.upsert_rank_cache(
                    reg["puuid"], "NA",
                    rank["tier"], rank["division"],
                    rank["lp"], rank["wins"], rank["losses"],
                )
                # Also refresh linked accounts
                linked = await self.bot.db.get_linked_accounts(reg["discord_id"])
                for acct in linked:
                    try:
                        r = await self.bot.riot.refresh_rank(
                            acct["puuid"], acct["region"]
                        )
                        await self.bot.db.upsert_rank_cache(
                            acct["puuid"], acct["region"],
                            r["tier"], r["division"],
                            r["lp"], r["wins"], r["losses"],
                        )
                    except RiotAPIError:
                        pass
                success += 1
            except RiotAPIError as e:
                log.warning(
                    "force-refresh failed for %s: %s", reg["game_name"], e
                )
                failed += 1

        result = f"✅ Refreshed **{success}** player(s)."
        if failed:
            result += f" ⚠️ Failed to refresh **{failed}** player(s) — check logs."
        await interaction.edit_original_response(content=result)

    # ------------------------------------------------------------------ #
    # /remove-player                                                        #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="remove-player",
        description="Remove a player from the global leaderboard (admin only).",
    )
    @app_commands.describe(member="The Discord member to remove")
    @app_commands.default_permissions(manage_guild=True)
    async def remove_player(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        removed = await self.bot.db.delete_registration(member.id)
        if removed:
            await interaction.response.send_message(
                f"✅ **{member.display_name}** has been removed from the leaderboard.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"**{member.display_name}** is not registered on the leaderboard.",
                ephemeral=True,
            )

    # ------------------------------------------------------------------ #
    # /leaderboard-status                                                   #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="leaderboard-status",
        description="Show the current auto-post configuration for this server.",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def leaderboard_status(self, interaction: discord.Interaction) -> None:
        settings = await self.bot.db.get_guild_settings(interaction.guild_id)
        registrations = await self.bot.db.get_all_registrations()

        embed = discord.Embed(title="⚙️ Leaderboard Configuration", color=0x5865F2)

        if settings and settings.get("channel_id"):
            ch = self.bot.get_channel(settings["channel_id"])
            ch_mention = ch.mention if ch else f"Unknown (ID: {settings['channel_id']})"
            interval_min = (settings.get("post_interval") or 3600) // 60
            embed.add_field(name="Auto-post Channel", value=ch_mention, inline=True)
            embed.add_field(
                name="Interval", value=f"{interval_min} minutes", inline=True
            )
        else:
            embed.add_field(
                name="Auto-post",
                value="Disabled — use `/set-channel` to enable",
                inline=False,
            )

        embed.add_field(
            name="Registered Players (Global)",
            value=str(len(registrations)),
            inline=True,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
