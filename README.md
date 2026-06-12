# Spectro

Spectro is a Windows automation assistant for Brawl Stars. It runs through an Android emulator, reads the current game state from the screen, and controls movement/actions through the configured emulator key layout.

Dev: t.me/forget_git

## Features

- Brawlball-focused gameplay automation
- Ball, wall, player, enemy and ability detection
- Brawler queue with trophy/win targets
- Push All queue builder for opened brawlers below a selected trophy target
- Match history and trophy tracking
- Discord notifications and Discord remote control
- Telegram remote control
- Developer tab with tests, utilities and dataset capture tools
- ONNX Runtime backend auto-selection with CPU fallback

## Requirements

- Windows 64-bit
- Python 3.11
- Android emulator at 1920x1080
- Windows display scaling set to 100%

Supported emulator profiles:

- LDPlayer
- MuMu
- BlueStacks
- Nox
- MEmu
- GameLoop

## Quick start

```bat
setup_venv.bat
start.bat
```

Manual start:

```bat
python setup.py --spectro-install
python run.py
```

## Basic setup

1. Install Python 3.11.
2. Install and configure an Android emulator.
3. Set emulator resolution to 1920x1080.
4. Open Brawl Stars in the emulator.
5. Start Spectro.
6. In Overview, choose emulator and game mode.
7. Configure Brawler Queue if needed.
8. Press Start.

## Important config files

| File | Purpose |
| --- | --- |
| `cfg/general_config.toml` | Emulator, performance, GPU/CPU, debug options |
| `cfg/bot_config.toml` | Gameplay behavior and mode settings |
| `cfg/brawler_pick.toml` | Brawler queue data, created/updated by GUI |
| `cfg/time_tresholds.toml` | Timers for state checks and actions |
| `cfg/brawl_stars_api.toml` | Optional Brawl Stars API token and player tag |
| `cfg/discord_config.toml` | Discord notifications and control |
| `cfg/telegram_config.toml` | Telegram remote control |
| `cfg/update_config.toml` | Optional updater settings |

## Brawl Stars API

The API config is optional, but recommended for trophy autofill and Push All. Fill:

```toml
api_token = ""
player_tag = "#YOURTAG"
timeout_seconds = 15
```

## Telegram control

Fill `cfg/telegram_config.toml` and set:

```toml
[telegram]
enabled = "yes"
bot_token = "YOUR_BOT_TOKEN"
chat_id = "YOUR_CHAT_ID"
```

Commands:

```text
/menu
/status
/pause
/resume
/stop
```

## Developer mode

Developer tab is hidden by default. Enable it in `cfg/general_config.toml`:

```toml
developer = "yes"
```

It contains test runners, dataset capture tools and utility launchers.

## Tests

```bat
python -m unittest discover -s tests
```

## Notes

- Keep personal API tokens and bot tokens out of commits.
- The committed config files are sanitized defaults.
- Runtime folders such as `logs`, `debug_frames`, `datasets` and `runs` are ignored by git.
