from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN: str = os.environ["DISCORD_TOKEN"]
RIOT_API_KEY: str = os.environ["RIOT_API_KEY"]
DB_PATH: str = os.getenv("DB_PATH", "tft.db")
CACHE_TTL: int = int(os.getenv("CACHE_TTL", "300"))  # seconds; default 5 minutes

PLAYERS_PER_PAGE = 10        # players per page for /leaderboard (ephemeral)
AUTO_POST_PLAYERS_PER_PAGE = 100  # players shown in the auto-posted channel message

# Maps our region key → Riot platform host (summoner/league endpoints)
PLATFORM_HOSTS: dict[str, str] = {
    "NA": "na1.api.riotgames.com",
    "KR": "kr.api.riotgames.com",
    "EUW": "euw1.api.riotgames.com",
    "EUNE": "eun1.api.riotgames.com",
    "BR": "br1.api.riotgames.com",
    "JP": "jp1.api.riotgames.com",
    "LAN": "la1.api.riotgames.com",
    "LAS": "la2.api.riotgames.com",
    "OCE": "oc1.api.riotgames.com",
    "TR": "tr1.api.riotgames.com",
    "RU": "ru.api.riotgames.com",
}

# Maps our region key → Riot regional routing host (account-v1 / PUUID lookup)
REGIONAL_HOSTS: dict[str, str] = {
    "NA": "americas.api.riotgames.com",
    "BR": "americas.api.riotgames.com",
    "LAN": "americas.api.riotgames.com",
    "LAS": "americas.api.riotgames.com",
    "KR": "asia.api.riotgames.com",
    "JP": "asia.api.riotgames.com",
    "EUW": "europe.api.riotgames.com",
    "EUNE": "europe.api.riotgames.com",
    "TR": "europe.api.riotgames.com",
    "RU": "europe.api.riotgames.com",
    "OCE": "sea.api.riotgames.com",
}

VALID_REGIONS = list(PLATFORM_HOSTS.keys())

# Ordered lowest → highest for scoring
TIER_ORDER: list[str] = [
    "UNRANKED", "IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM",
    "EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER",
]
# TIER_ORDER: list[str] = [
#     "IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM",
#     "EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER",
# ]
RANK_ORDER: list[str] = ["IV", "III", "II", "I"]

TIER_EMOJIS: dict[str, str] = {
    "UNRANKED": "<:TFT_Unranked:1488456833730478110>",
    "IRON": "<:TFT_Iron:1488456829393698958>",
    "BRONZE": "<:TFT_Bronze:1488456823987109908>",
    "SILVER": "<:TFT_Silver:1488456832803405864>",
    "GOLD": "<:TFT_Gold:1488456827300483212>",
    "PLATINUM": "<:TFT_Platinum:1488456831318884383>",
    "EMERALD": "<:TFT_Emerald:1488456826256363581>",
    "DIAMOND": "<:TFT_Diamond:1488456825501257859>",
    "MASTER": "<:TFT_Master:1488456830488154263>",
    "GRANDMASTER": "<:TFT_Grandmaster:1488456828600975400>",
    "CHALLENGER": "<:TFT_Challenger:1488456824821649408>",
}
# TIER_EMOJIS: dict[str, str] = {
#     "IRON": "⬛",
#     "BRONZE": "🟫",
#     "SILVER": "⬜",
#     "GOLD": "🟨",
#     "PLATINUM": "🩵",
#     "EMERALD": "💚",
#     "DIAMOND": "💙",
#     "MASTER": "🟣",
#     "GRANDMASTER": "🟥",
#     "CHALLENGER": "⭐",
# }

# Embed accent color per top-ranked tier
TIER_COLORS: dict[str, int] = {
    "UNRANKED": 0x2B2D31,
    "IRON": 0x8B8B8B,
    "BRONZE": 0xCD7F32,
    "SILVER": 0xC0C0C0,
    "GOLD": 0xFFD700,
    "PLATINUM": 0x00B4D8,
    "EMERALD": 0x50C878,
    "DIAMOND": 0xB9F2FF,
    "MASTER": 0x9932CC,
    "GRANDMASTER": 0xFF4500,
    "CHALLENGER": 0xFFD700,
}


def rank_score(tier: str | None, division: str | None, lp: int) -> int:
    """Return a numeric score for sorting; unranked players score -1."""
    if not tier:
        return -1
    tier_val = TIER_ORDER.index(tier) if tier in TIER_ORDER else -1
    div_val = RANK_ORDER.index(division) if division in RANK_ORDER else 0
    return tier_val * 10_000 + div_val * 400 + (lp or 0)


def format_rank(tier: str | None, division: str | None, lp: int) -> str:
    """Return a human-readable rank string."""
    if not tier:
        emoji = TIER_EMOJIS.get("UNRANKED", "")
        return f"{emoji} Unranked".strip()
    emoji = TIER_EMOJIS.get(tier, "")
    tier_str = tier.title()
    if tier in ("MASTER", "GRANDMASTER", "CHALLENGER"):
        return f"{emoji} {tier_str} {lp:,} LP"
    return f"{emoji} {tier_str} {division} {lp:,} LP"


MEDALS: dict[int, str] = {1: "🥇", 2: "🥈", 3: "🥉"}
