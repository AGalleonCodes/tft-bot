from __future__ import annotations

import time
from typing import Any

import aiosqlite

from config import DB_PATH


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _create_tables(self) -> None:
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS registrations (
                guild_id       INTEGER NOT NULL,
                discord_id     INTEGER NOT NULL,
                game_name      TEXT    NOT NULL,
                tag_line       TEXT    NOT NULL,
                puuid          TEXT    NOT NULL,
                PRIMARY KEY (guild_id, discord_id)
            );

            CREATE TABLE IF NOT EXISTS linked_accounts (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id       INTEGER NOT NULL,
                discord_id     INTEGER NOT NULL,
                region         TEXT    NOT NULL,
                game_name      TEXT    NOT NULL,
                tag_line       TEXT    NOT NULL,
                puuid          TEXT    NOT NULL,
                UNIQUE (guild_id, discord_id, region),
                FOREIGN KEY (guild_id, discord_id)
                    REFERENCES registrations(guild_id, discord_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS rank_cache (
                puuid          TEXT    NOT NULL,
                region         TEXT    NOT NULL,
                tier           TEXT,
                division       TEXT,
                lp             INTEGER DEFAULT 0,
                wins           INTEGER DEFAULT 0,
                losses         INTEGER DEFAULT 0,
                updated_at     INTEGER NOT NULL,
                PRIMARY KEY (puuid, region)
            );

            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id            INTEGER PRIMARY KEY,
                channel_id          INTEGER,
                post_interval       INTEGER DEFAULT 3600,
                last_post_at        INTEGER DEFAULT 0,
                last_message_id     INTEGER
            );
        """)
        await self._db.commit()

    # ------------------------------------------------------------------ #
    # Registrations                                                         #
    # ------------------------------------------------------------------ #

    async def upsert_registration(
        self,
        guild_id: int,
        discord_id: int,
        game_name: str,
        tag_line: str,
        puuid: str,
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO registrations (guild_id, discord_id, game_name, tag_line, puuid)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, discord_id) DO UPDATE SET
                game_name = excluded.game_name,
                tag_line  = excluded.tag_line,
                puuid     = excluded.puuid
            """,
            (guild_id, discord_id, game_name, tag_line, puuid),
        )
        await self._db.commit()

    async def delete_registration(self, guild_id: int, discord_id: int) -> bool:
        cursor = await self._db.execute(
            "DELETE FROM registrations WHERE guild_id = ? AND discord_id = ?",
            (guild_id, discord_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_registration(
        self, guild_id: int, discord_id: int
    ) -> dict[str, Any] | None:
        async with self._db.execute(
            "SELECT * FROM registrations WHERE guild_id = ? AND discord_id = ?",
            (guild_id, discord_id),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_all_registrations(self, guild_id: int) -> list[dict[str, Any]]:
        async with self._db.execute(
            "SELECT * FROM registrations WHERE guild_id = ?", (guild_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Linked accounts                                                       #
    # ------------------------------------------------------------------ #

    async def upsert_linked_account(
        self,
        guild_id: int,
        discord_id: int,
        region: str,
        game_name: str,
        tag_line: str,
        puuid: str,
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO linked_accounts
                (guild_id, discord_id, region, game_name, tag_line, puuid)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, discord_id, region) DO UPDATE SET
                game_name = excluded.game_name,
                tag_line  = excluded.tag_line,
                puuid     = excluded.puuid
            """,
            (guild_id, discord_id, region, game_name, tag_line, puuid),
        )
        await self._db.commit()

    async def delete_linked_account(
        self, guild_id: int, discord_id: int, region: str
    ) -> bool:
        cursor = await self._db.execute(
            "DELETE FROM linked_accounts WHERE guild_id = ? AND discord_id = ? AND region = ?",
            (guild_id, discord_id, region),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_linked_accounts(
        self, guild_id: int, discord_id: int
    ) -> list[dict[str, Any]]:
        async with self._db.execute(
            "SELECT * FROM linked_accounts WHERE guild_id = ? AND discord_id = ?",
            (guild_id, discord_id),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Rank cache                                                            #
    # ------------------------------------------------------------------ #

    async def upsert_rank_cache(
        self,
        puuid: str,
        region: str,
        tier: str | None,
        division: str | None,
        lp: int,
        wins: int,
        losses: int,
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO rank_cache (puuid, region, tier, division, lp, wins, losses, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(puuid, region) DO UPDATE SET
                tier       = excluded.tier,
                division   = excluded.division,
                lp         = excluded.lp,
                wins       = excluded.wins,
                losses     = excluded.losses,
                updated_at = excluded.updated_at
            """,
            (puuid, region, tier, division, lp, wins, losses, int(time.time())),
        )
        await self._db.commit()

    async def get_rank_cache(
        self, puuid: str, region: str
    ) -> dict[str, Any] | None:
        async with self._db.execute(
            "SELECT * FROM rank_cache WHERE puuid = ? AND region = ?",
            (puuid, region),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_stale_cache_entries(self, cutoff: int) -> list[dict[str, Any]]:
        """Return (puuid, region) pairs whose cache is older than cutoff and still active.

        Uses EXISTS to avoid duplicates when the same account appears in multiple guilds.
        """
        async with self._db.execute(
            """
            SELECT rc.puuid, rc.region
            FROM rank_cache rc
            WHERE rc.updated_at < ?
              AND (
                (rc.region = 'NA' AND EXISTS (
                    SELECT 1 FROM registrations WHERE puuid = rc.puuid
                ))
                OR (rc.region != 'NA' AND EXISTS (
                    SELECT 1 FROM linked_accounts WHERE puuid = rc.puuid AND region = rc.region
                ))
              )
            """,
            (cutoff,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def invalidate_guild_cache(self, guild_id: int) -> None:
        """Set all cache entries for a guild's players to expired (updated_at = 0)."""
        await self._db.execute(
            """
            UPDATE rank_cache SET updated_at = 0
            WHERE puuid IN (SELECT puuid FROM registrations WHERE guild_id = ?)
               OR puuid IN (SELECT puuid FROM linked_accounts WHERE guild_id = ?)
            """,
            (guild_id, guild_id),
        )
        await self._db.commit()

    # ------------------------------------------------------------------ #
    # Guild settings                                                        #
    # ------------------------------------------------------------------ #

    async def get_guild_settings(self, guild_id: int) -> dict[str, Any] | None:
        async with self._db.execute(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def upsert_guild_settings(self, guild_id: int, **kwargs: Any) -> None:
        existing = await self.get_guild_settings(guild_id)
        if existing:
            if not kwargs:
                return
            set_clause = ", ".join(f"{k} = ?" for k in kwargs)
            await self._db.execute(
                f"UPDATE guild_settings SET {set_clause} WHERE guild_id = ?",
                [*kwargs.values(), guild_id],
            )
        else:
            kwargs["guild_id"] = guild_id
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" * len(kwargs))
            await self._db.execute(
                f"INSERT INTO guild_settings ({cols}) VALUES ({placeholders})",
                list(kwargs.values()),
            )
        await self._db.commit()

    async def get_guilds_due_for_post(self, now: int) -> list[dict[str, Any]]:
        """Return guild settings rows where auto-post is configured and interval has elapsed."""
        async with self._db.execute(
            """
            SELECT * FROM guild_settings
            WHERE channel_id IS NOT NULL
              AND post_interval > 0
              AND (? - last_post_at) >= post_interval
            """,
            (now,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
