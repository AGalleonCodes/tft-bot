from __future__ import annotations

import logging
import time
from typing import Any

import aiosqlite

from config import DB_PATH

log = logging.getLogger(__name__)


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
        # Check if we need to migrate from the old per-guild schema
        async with self._db.execute("PRAGMA table_info(registrations)") as cur:
            cols = [row[1] for row in await cur.fetchall()]

        if "guild_id" in cols:
            await self._migrate_to_global()

        # Rename game_name → in_game_name if needed
        async with self._db.execute("PRAGMA table_info(registrations)") as cur:
            cols = [row[1] for row in await cur.fetchall()]
        if "game_name" in cols:
            await self._migrate_rename_game_name()

        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS registrations (
                discord_id     INTEGER PRIMARY KEY,
                in_game_name   TEXT    NOT NULL,
                tag_line       TEXT    NOT NULL,
                puuid          TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS linked_accounts (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id     INTEGER NOT NULL,
                region         TEXT    NOT NULL,
                in_game_name   TEXT    NOT NULL,
                tag_line       TEXT    NOT NULL,
                puuid          TEXT    NOT NULL,
                UNIQUE (discord_id, region),
                FOREIGN KEY (discord_id)
                    REFERENCES registrations(discord_id)
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

    async def _migrate_to_global(self) -> None:
        """Migrate from per-guild schema (guild_id in registrations/linked_accounts) to global."""
        log.info("Migrating database to global (guild-agnostic) schema...")
        await self._db.execute("PRAGMA foreign_keys=OFF")
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS registrations_new (
                discord_id   INTEGER PRIMARY KEY,
                in_game_name TEXT NOT NULL,
                tag_line     TEXT NOT NULL,
                puuid        TEXT NOT NULL
            );
            INSERT OR IGNORE INTO registrations_new (discord_id, in_game_name, tag_line, puuid)
                SELECT discord_id, game_name, tag_line, puuid FROM registrations;
            DROP TABLE registrations;
            ALTER TABLE registrations_new RENAME TO registrations;

            CREATE TABLE IF NOT EXISTS linked_accounts_new (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id   INTEGER NOT NULL,
                region       TEXT NOT NULL,
                in_game_name TEXT NOT NULL,
                tag_line     TEXT NOT NULL,
                puuid        TEXT NOT NULL,
                UNIQUE (discord_id, region),
                FOREIGN KEY (discord_id) REFERENCES registrations(discord_id) ON DELETE CASCADE
            );
            INSERT OR IGNORE INTO linked_accounts_new (discord_id, region, in_game_name, tag_line, puuid)
                SELECT discord_id, region, game_name, tag_line, puuid FROM linked_accounts;
            DROP TABLE linked_accounts;
            ALTER TABLE linked_accounts_new RENAME TO linked_accounts;
        """)
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.commit()
        log.info("Migration to global schema complete.")

    async def _migrate_rename_game_name(self) -> None:
        """Rename game_name column to in_game_name in registrations and linked_accounts."""
        log.info("Renaming game_name → in_game_name...")
        await self._db.executescript("""
            ALTER TABLE registrations RENAME COLUMN game_name TO in_game_name;
            ALTER TABLE linked_accounts RENAME COLUMN game_name TO in_game_name;
        """)
        await self._db.commit()
        log.info("Column rename complete.")

    # ------------------------------------------------------------------ #
    # Registrations                                                         #
    # ------------------------------------------------------------------ #

    async def upsert_registration(
        self,
        discord_id: int,
        in_game_name: str,
        tag_line: str,
        puuid: str,
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO registrations (discord_id, in_game_name, tag_line, puuid)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET
                in_game_name = excluded.in_game_name,
                tag_line     = excluded.tag_line,
                puuid        = excluded.puuid
            """,
            (discord_id, in_game_name, tag_line, puuid),
        )
        await self._db.commit()

    async def delete_registration(self, discord_id: int) -> bool:
        cursor = await self._db.execute(
            "DELETE FROM registrations WHERE discord_id = ?",
            (discord_id,),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_registration(self, discord_id: int) -> dict[str, Any] | None:
        async with self._db.execute(
            "SELECT * FROM registrations WHERE discord_id = ?",
            (discord_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_all_registrations(self) -> list[dict[str, Any]]:
        async with self._db.execute("SELECT * FROM registrations") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Linked accounts                                                       #
    # ------------------------------------------------------------------ #

    async def upsert_linked_account(
        self,
        discord_id: int,
        region: str,
        in_game_name: str,
        tag_line: str,
        puuid: str,
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO linked_accounts
                (discord_id, region, in_game_name, tag_line, puuid)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(discord_id, region) DO UPDATE SET
                in_game_name = excluded.in_game_name,
                tag_line     = excluded.tag_line,
                puuid        = excluded.puuid
            """,
            (discord_id, region, in_game_name, tag_line, puuid),
        )
        await self._db.commit()

    async def delete_linked_account(self, discord_id: int, region: str) -> bool:
        cursor = await self._db.execute(
            "DELETE FROM linked_accounts WHERE discord_id = ? AND region = ?",
            (discord_id, region),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_linked_accounts(self, discord_id: int) -> list[dict[str, Any]]:
        async with self._db.execute(
            "SELECT * FROM linked_accounts WHERE discord_id = ?",
            (discord_id,),
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
        """Return (puuid, region) pairs whose cache is older than cutoff and still active."""
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

    async def invalidate_all_cache(self) -> None:
        """Set all cache entries for all registered players to expired (updated_at = 0)."""
        await self._db.execute(
            """
            UPDATE rank_cache SET updated_at = 0
            WHERE puuid IN (SELECT puuid FROM registrations)
               OR puuid IN (SELECT puuid FROM linked_accounts)
            """
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
