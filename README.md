# Spectro

Brawl Stars bot focused on **Brawlball** mode.

Focus areas:
- Brawlball logic — ball tracking, goal positioning, team play
- Bot logic and code improvements
- Clean, maintainable codebase

Version: `0.0.2`

---

## Requirements

- Windows 64-bit
- Python 3.11
- Android emulator (LDPlayer / MuMu) at 1920x1080

## Setup

Clone the repository and install dependencies in a virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Run Spectro:

```bash
python run.py
```

Optional local installer command:

```bash
python setup.py --spectro-install
```

## Config files

| File | Purpose |
|------|---------|
| `cfg/general_config.toml` | Emulator, performance, GPU/CPU |
| `cfg/bot_config.toml` | Gamemode, behavior |
| `cfg/discord_config.toml` | Discord notifications and control |
| `cfg/telegram_config.toml` | Telegram remote control |
| `cfg/brawl_stars_api.toml` | Trophy autofill and Push All |

## Telegram control

1. Create a bot via @BotFather, get the token
2. Open `cfg/telegram_config.toml`, fill `bot_token` and `chat_id`
3. Set `enabled = true`
4. Start Spectro

Commands: `/status` `/pause` `/resume` `/stop`

Polling is intentionally low-frequency to minimize internet usage.

## Brawl Stars API

Create a developer account at https://developer.brawlstars.com/  
Fill `cfg/brawl_stars_api.toml` for automatic trophy tracking.

## GitHub update

```bash
python tools/github_update.py --check
python tools/github_update.py
```

Set `repo = "owner/repo"` in `cfg/update_config.toml`.

## Tests

```bash
python -m unittest discover
```

GitHub Actions currently runs a lightweight syntax check on Windows. Full runtime tests require the Windows/emulator environment and project dependencies.

## Before publishing your fork

Do not commit personal tokens, webhooks or private player tags. The public config files should use placeholders such as `YOUR_BOT_TOKEN`, empty Discord tokens and `#YOUR_TAG`. Runtime folders such as `logs/`, `debug_frames/`, `runs/`, `datasets/` and local backups are ignored by Git.

## Architecture

```
spectro/
  main.py
  app/          runtime control, discord control
  control/      play, navigation, window control
  core/         utils, logging, performance
  game/         stage manager, trophies, brawltracker
  gui/          hub, login, brawler selection
  integrations/ discord, telegram, api sync
  vision/       detection, state finder, HP
```

---

Author: forgeter - tg @frendls
