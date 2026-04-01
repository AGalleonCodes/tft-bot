# TFT Rank Tracker

A Discord bot that tracks Teamfight Tactics ranks for your server members and displays a live leaderboard sorted from highest to lowest rank.

## Features

- **Self-registration** — players register their own NA Riot account with a slash command
- **Live leaderboard** — paginated embed sorted by rank, refreshed automatically
- **Auto-posting** — bot posts/edits the leaderboard in a configured channel on a schedule
- **Smart caching** — rank data is cached for 5 minutes to stay within Riot API rate limits; a background task refreshes stale entries automatically
- **Linked regions** — players can attach a non-NA account (KR, EUW, etc.) to display alongside their NA rank for visual context
- **Per-server data** — each Discord server has its own independent leaderboard

## Setup

### 1. Prerequisites

- Python 3.9+
- A [Discord bot token](https://discord.com/developers/applications)
- A [Riot Games API key](https://developer.riotgames.com/)

> **Note:** Developer API keys from Riot expire every 24 hours. For a permanent deployment you will need to apply for a production key through the Riot developer portal.

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials:

```env
DISCORD_TOKEN=your_discord_bot_token_here
RIOT_API_KEY=RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Optional variables (defaults shown):

```env
DB_PATH=tft.db       # SQLite database file path
CACHE_TTL=300        # Seconds before a player's rank is re-fetched (default: 5 min)
```

### 4. Invite the bot to your server

In the Discord Developer Portal, under **OAuth2 → URL Generator**, select the following scopes and permissions:

- **Scopes:** `bot`, `applications.commands`
- **Bot Permissions:** `Send Messages`, `Embed Links`, `Read Message History`

### 5. Run the bot

```bash
python3 bot.py
```

On first start the bot will create `tft.db`, sync slash commands globally (propagation takes up to 1 hour), and begin the background refresh loop.

---

## Commands

### Player commands

| Command | Description |
|---|---|
| `/register <in_game_name> <tag_line>` | Register your NA TFT account to this server's leaderboard |
| `/unregister` | Remove yourself from this server's leaderboard |
| `/link-region <region> <in_game_name> <tag_line>` | Attach a non-NA account to display alongside your NA rank |
| `/unlink-region <region>` | Remove a linked regional account |
| `/my-accounts` | View your registered NA account and all linked accounts with their ranks |
| `/leaderboard` | Show the full paginated leaderboard for this server |
| `/rank [member]` | Show the current rank for yourself or another server member |

### Admin commands

> Requires the **Manage Server** permission.

| Command | Description |
|---|---|
| `/set-channel [channel]` | Set the channel where the leaderboard is auto-posted (defaults to current channel) |
| `/set-interval <minutes>` | Set how often the leaderboard is auto-posted (10–1440 minutes) |
| `/disable-autopost` | Stop automatic leaderboard posting for this server |
| `/force-post` | Immediately post the leaderboard to the configured channel |
| `/force-refresh` | Force all player ranks to re-fetch from Riot API right now |
| `/remove-player <member>` | Remove a player from the leaderboard (admin override) |
| `/leaderboard-status` | Show the current auto-post configuration and player count |

---

## Supported Regions

The bot supports linking accounts from any of the following regions:

`KR` `EUW` `EUNE` `BR` `JP` `LAN` `LAS` `OCE` `TR` `RU`

NA is always the primary region used for leaderboard ranking. Linked accounts from other regions are displayed for context only and do not affect rank ordering.

---

## How It Works

### Registration flow

1. User runs `/register SummonerName NA1`
2. Bot resolves the Riot ID → PUUID via `americas.api.riotgames.com`
3. Bot resolves the PUUID → summoner ID via `na1.api.riotgames.com`
4. Bot fetches the TFT rank and stores everything in the local database
5. Confirmation embed is shown with the player's current rank

### Caching & background refresh

Rank data is stored in a local SQLite database. A background task runs every 60 seconds and refreshes any cache entries older than `CACHE_TTL` (default 5 minutes). This means:

- `/leaderboard` and `/rank` respond instantly from cache
- Ranks are at most 5 minutes stale
- A burst of players using `/leaderboard` simultaneously does not spike API calls

### Auto-posting

When a channel and interval are configured with `/set-channel` and `/set-interval`, the bot will post the leaderboard on that schedule. It edits the existing message if it is still present in the channel, avoiding clutter. Auto-posted messages show page 1 of the leaderboard; use `/leaderboard` for interactive pagination.

### Rank ordering

Players are sorted by a numeric score derived from their tier, division, and LP:

```
score = tier_index × 10,000 + division_index × 400 + LP
```

Tiers rank from Iron (0) to Challenger (9). Unranked players appear at the bottom.

---

## Project Structure

```
tft-bot-claude/
├── bot.py                  # Entry point, TFTBot class, background task
├── config.py               # Constants, region maps, rank helpers
├── database.py             # SQLite schema and all data access methods
├── riot_client.py          # Riot Games API wrapper
├── cogs/
│   ├── registration.py     # /register, /unregister, /link-region, /unlink-region, /my-accounts
│   ├── leaderboard.py      # /leaderboard, /rank, PaginatedLeaderboard view, auto-post helper
│   └── admin.py            # Admin configuration and management commands
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Troubleshooting

**Commands don't appear in Discord**
Global slash command sync can take up to 1 hour to propagate. For instant sync during development, replace the `await self.tree.sync()` call in `bot.py` with a guild-specific sync:
```python
await self.tree.sync(guild=discord.Object(id=YOUR_GUILD_ID))
```

**`403 Forbidden` from Riot API**
Your developer key may have expired (they last 24 hours). Regenerate it at [developer.riotgames.com](https://developer.riotgames.com).

**`404 Not Found` when registering**
Double-check the game name and tag line. The tag is the part after `#` in your Riot ID — for NA accounts this is usually `NA1` but can be any custom tag.

**Bot can't edit its auto-post message**
Make sure the bot has `Read Message History` and `Embed Links` permissions in the configured channel.
