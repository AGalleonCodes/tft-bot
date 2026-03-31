from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from config import PLATFORM_HOSTS, REGIONAL_HOSTS

log = logging.getLogger(__name__)


class RiotAPIError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"Riot API {status}: {message}")


class NotFoundError(RiotAPIError):
    pass


class RateLimitError(RiotAPIError):
    def __init__(self, retry_after: int = 5):
        self.retry_after = retry_after
        super().__init__(429, f"Rate limited; retry after {retry_after}s")


class RiotClient:
    def __init__(self, session: aiohttp.ClientSession, api_key: str):
        self._session = session
        self._api_key = api_key
        self._sem = asyncio.Semaphore(5)

    async def _get(self, url: str) -> Any:
        headers = {"X-Riot-Token": self._api_key}
        async with self._sem:
            async with self._session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.json()
                if resp.status == 404:
                    raise NotFoundError(404, "Not found")
                if resp.status == 429:
                    retry_after = int(resp.headers.get("Retry-After", "5"))
                    raise RateLimitError(retry_after)
                if resp.status == 403:
                    raise RiotAPIError(403, "API key forbidden — check your Riot developer key")
                if resp.status == 401:
                    raise RiotAPIError(401, "API key unauthorized — key may be expired")
                text = await resp.text()
                raise RiotAPIError(resp.status, text[:200])

    async def get_account_by_riot_id(
        self, game_name: str, tag_line: str, region: str = "NA"
    ) -> dict[str, Any]:
        """Resolves gameName + tagLine → account data including puuid."""
        regional = REGIONAL_HOSTS.get(region.upper(), "americas.api.riotgames.com")
        url = (
            f"https://{regional}/riot/account/v1/accounts/by-riot-id"
            f"/{game_name}/{tag_line}"
        )
        return await self._get(url)

    async def get_tft_rank_by_puuid(
        self, puuid: str, region: str = "NA"
    ) -> dict[str, Any] | None:
        """
        Returns the RANKED_TFT league entry for a puuid, or None if unranked.
        Uses the PUUID-based endpoint added in Riot's 2024 API migration.
        """
        platform = PLATFORM_HOSTS.get(region.upper(), "na1.api.riotgames.com")
        # url = f"https://{platform}/tft/league/v1/entries/by-puuid/{puuid}"
        url = f"https://{platform}/tft/league/v1/by-puuid/{puuid}"
        entries: list[dict] = await self._get(url)
        return next(
            (e for e in entries if e.get("queueType") == "RANKED_TFT"), None
        )

    async def resolve_player(
        self, game_name: str, tag_line: str, region: str = "NA"
    ) -> dict[str, Any]:
        """
        Full resolution: gameName#tagLine → {puuid, tier, division, lp, wins, losses}.
        Raises RiotAPIError on any failure.
        """
        account = await self.get_account_by_riot_id(game_name, tag_line, region)
        puuid: str = account["puuid"]
        # Use canonical casing returned by Riot
        game_name = account["gameName"]
        tag_line = account["tagLine"]

        rank_entry = await self.get_tft_rank_by_puuid(puuid, region)

        return {
            "puuid": puuid,
            "game_name": game_name,
            "tag_line": tag_line,
            "tier": rank_entry["tier"] if rank_entry else None,
            "division": rank_entry["rank"] if rank_entry else None,
            "lp": rank_entry["leaguePoints"] if rank_entry else 0,
            "wins": rank_entry["wins"] if rank_entry else 0,
            "losses": rank_entry["losses"] if rank_entry else 0,
        }

    async def refresh_rank(self, puuid: str, region: str = "NA") -> dict[str, Any]:
        """
        Fetch only the rank for an already-resolved player by PUUID.
        Returns dict with tier/division/lp/wins/losses (tier is None if unranked).
        """
        rank_entry = await self.get_tft_rank_by_puuid(puuid, region)
        return {
            "tier": rank_entry["tier"] if rank_entry else None,
            "division": rank_entry["rank"] if rank_entry else None,
            "lp": rank_entry["leaguePoints"] if rank_entry else 0,
            "wins": rank_entry["wins"] if rank_entry else 0,
            "losses": rank_entry["losses"] if rank_entry else 0,
        }
