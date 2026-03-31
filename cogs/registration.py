from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import VALID_REGIONS, format_rank, TIER_COLORS
from riot_client import NotFoundError, RiotAPIError

log = logging.getLogger(__name__)


class Registration(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------ #
    # /register                                                             #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="register",
        description="Register your NA TFT account to this server's leaderboard.",
    )
    @app_commands.describe(
        game_name="Your Riot Games username (the part before #)",
        tag_line="Your Riot tag (the part after #, e.g. NA1)",
    )
    async def register(
        self,
        interaction: discord.Interaction,
        game_name: str,
        tag_line: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            data = await self.bot.riot.resolve_player(game_name, tag_line, region="NA")
        except NotFoundError:
            await interaction.followup.send(
                f"Could not find Riot account **{game_name}#{tag_line}**. "
                "Double-check your username and tag.",
                ephemeral=True,
            )
            return
        except RiotAPIError as e:
            await interaction.followup.send(
                f"Riot API error: {e.message}", ephemeral=True
            )
            return

        await self.bot.db.upsert_registration(
            guild_id=interaction.guild_id,
            discord_id=interaction.user.id,
            game_name=data["game_name"],
            tag_line=data["tag_line"],
            puuid=data["puuid"],
        )
        await self.bot.db.upsert_rank_cache(
            puuid=data["puuid"],
            region="NA",
            tier=data["tier"],
            division=data["division"],
            lp=data["lp"],
            wins=data["wins"],
            losses=data["losses"],
        )

        rank_str = format_rank(data["tier"], data["division"], data["lp"])
        color = TIER_COLORS.get(data["tier"] or "", 0x2B2D31)
        embed = discord.Embed(
            title="✅ Registered!",
            description=(
                f"**{data['game_name']}#{data['tag_line']}** has been added to "
                f"**{interaction.guild.name}**'s TFT leaderboard."
            ),
            color=color,
        )
        embed.add_field(name="Current Rank", value=rank_str, inline=True)
        if data["tier"]:
            total = (data["wins"] or 0) + (data["losses"] or 0)
            if total:
                wr = round(data["wins"] / total * 100, 1)
                embed.add_field(
                    name="Win Rate",
                    value=f"{wr}% ({data['wins']}W / {data['losses']}L)",
                    inline=True,
                )
        embed.set_footer(text="Use /link-region to link your main account in another region.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    # /unregister                                                           #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="unregister",
        description="Remove yourself from this server's TFT leaderboard.",
    )
    async def unregister(self, interaction: discord.Interaction) -> None:
        removed = await self.bot.db.delete_registration(
            interaction.guild_id, interaction.user.id
        )
        if removed:
            await interaction.response.send_message(
                "You have been removed from this server's leaderboard.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "You are not registered on this server's leaderboard.", ephemeral=True
            )

    # ------------------------------------------------------------------ #
    # /link-region                                                          #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="link-region",
        description="Link a TFT account in another region to display alongside your NA rank.",
    )
    @app_commands.describe(
        region="The region of the account you want to link (e.g. KR, EUW, EUNE)",
        game_name="Riot username for that account (part before #)",
        tag_line="Riot tag for that account (part after #)",
    )
    @app_commands.choices(
        region=[app_commands.Choice(name=r, value=r) for r in VALID_REGIONS if r != "NA"]
    )
    async def link_region(
        self,
        interaction: discord.Interaction,
        region: str,
        game_name: str,
        tag_line: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        # Must be registered on this server first
        reg = await self.bot.db.get_registration(
            interaction.guild_id, interaction.user.id
        )
        if not reg:
            await interaction.followup.send(
                "You need to `/register` your NA account before linking other regions.",
                ephemeral=True,
            )
            return

        try:
            data = await self.bot.riot.resolve_player(game_name, tag_line, region=region)
        except NotFoundError:
            await interaction.followup.send(
                f"Could not find account **{game_name}#{tag_line}** in **{region}**.",
                ephemeral=True,
            )
            return
        except RiotAPIError as e:
            await interaction.followup.send(
                f"Riot API error: {e.message}", ephemeral=True
            )
            return

        await self.bot.db.upsert_linked_account(
            guild_id=interaction.guild_id,
            discord_id=interaction.user.id,
            region=region,
            game_name=data["game_name"],
            tag_line=data["tag_line"],
            puuid=data["puuid"],
        )
        await self.bot.db.upsert_rank_cache(
            puuid=data["puuid"],
            region=region,
            tier=data["tier"],
            division=data["division"],
            lp=data["lp"],
            wins=data["wins"],
            losses=data["losses"],
        )

        rank_str = format_rank(data["tier"], data["division"], data["lp"])
        embed = discord.Embed(
            title=f"✅ {region} Account Linked",
            description=(
                f"**{data['game_name']}#{data['tag_line']}** ({region}) will appear "
                "alongside your NA rank on the leaderboard."
            ),
            color=TIER_COLORS.get(data["tier"] or "", 0x2B2D31),
        )
        embed.add_field(name=f"{region} Rank", value=rank_str, inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    # /unlink-region                                                        #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="unlink-region",
        description="Remove a linked account in another region.",
    )
    @app_commands.describe(region="The region to unlink")
    @app_commands.choices(
        region=[app_commands.Choice(name=r, value=r) for r in VALID_REGIONS if r != "NA"]
    )
    async def unlink_region(
        self, interaction: discord.Interaction, region: str
    ) -> None:
        removed = await self.bot.db.delete_linked_account(
            interaction.guild_id, interaction.user.id, region
        )
        if removed:
            await interaction.response.send_message(
                f"Your **{region}** linked account has been removed.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"You don't have a **{region}** account linked.", ephemeral=True
            )

    # ------------------------------------------------------------------ #
    # /my-accounts                                                          #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="my-accounts",
        description="View your registered NA account and all linked regional accounts.",
    )
    async def my_accounts(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        reg = await self.bot.db.get_registration(
            interaction.guild_id, interaction.user.id
        )
        if not reg:
            await interaction.followup.send(
                "You are not registered. Use `/register` to add your NA account.",
                ephemeral=True,
            )
            return

        # Fetch NA rank from cache
        na_cache = await self.bot.db.get_rank_cache(reg["puuid"], "NA")
        na_rank = (
            format_rank(
                na_cache["tier"], na_cache["division"], na_cache["lp"]
            )
            if na_cache
            else "Unranked"
        )

        embed = discord.Embed(
            title=f"Accounts for {interaction.user.display_name}",
            color=TIER_COLORS.get(
                (na_cache or {}).get("tier") or "", 0x2B2D31
            ),
        )
        embed.add_field(
            name="🇺🇸 NA (Primary)",
            value=f"**{reg['game_name']}#{reg['tag_line']}**\n{na_rank}",
            inline=False,
        )

        linked = await self.bot.db.get_linked_accounts(
            interaction.guild_id, interaction.user.id
        )
        for acct in linked:
            cache = await self.bot.db.get_rank_cache(acct["puuid"], acct["region"])
            rank_str = (
                format_rank(cache["tier"], cache["division"], cache["lp"])
                if cache
                else "Unranked"
            )
            embed.add_field(
                name=f"🌐 {acct['region']} (Linked)",
                value=f"**{acct['game_name']}#{acct['tag_line']}**\n{rank_str}",
                inline=False,
            )

        if not linked:
            embed.set_footer(
                text="Use /link-region to add accounts in other regions."
            )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Registration(bot))
