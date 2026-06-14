"""Config validation for Spectro.

Call validate_all_configs() at startup to catch bad config values before the
bot tries to use them mid-run.  Every problem is collected and printed at once
so the user can fix everything in one shot instead of chasing one error at a time.

Returns (errors: list[str], warnings: list[str]).
Raises SystemExit when any hard errors are found.
"""
from __future__ import annotations

import os
import sys
from typing import Any

from core.utils import load_toml_as_dict, config_bool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _e(errors: list, msg: str) -> None:
    errors.append(msg)

def _w(warnings: list, msg: str) -> None:
    warnings.append(msg)

def _load(path: str, errors: list) -> dict | None:
    try:
        return load_toml_as_dict(path)
    except FileNotFoundError:
        _e(errors, f"Config file not found: {path}")
        return None
    except Exception as exc:
        _e(errors, f"Could not parse {path}: {exc}")
        return None

def _require(cfg: dict, key: str, path: str, errors: list) -> Any:
    val = cfg.get(key)
    if val is None:
        _e(errors, f"{path}: required key '{key}' is missing.")
    return val

def _require_positive_number(cfg: dict, key: str, path: str, errors: list, allow_zero: bool = False) -> None:
    val = cfg.get(key)
    if val is None:
        _e(errors, f"{path}: required key '{key}' is missing.")
        return
    try:
        n = float(val)
        if allow_zero and n < 0:
            _e(errors, f"{path}: '{key}' must be >= 0, got {val!r}.")
        elif not allow_zero and n <= 0:
            _e(errors, f"{path}: '{key}' must be > 0, got {val!r}.")
    except (TypeError, ValueError):
        _e(errors, f"{path}: '{key}' must be a number, got {val!r}.")

def _require_non_negative_int(cfg: dict, key: str, path: str, errors: list) -> None:
    val = cfg.get(key)
    if val is None:
        _e(errors, f"{path}: required key '{key}' is missing.")
        return
    try:
        n = int(val)
        if n < 0:
            _e(errors, f"{path}: '{key}' must be >= 0, got {val!r}.")
    except (TypeError, ValueError):
        _e(errors, f"{path}: '{key}' must be an integer, got {val!r}.")

def _require_one_of(cfg: dict, key: str, allowed: tuple, path: str, errors: list, default: Any = None) -> None:
    val = cfg.get(key, default)
    if val is None:
        _e(errors, f"{path}: required key '{key}' is missing.")
        return
    if str(val).strip().lower() not in [str(a).lower() for a in allowed]:
        _e(errors, f"{path}: '{key}' must be one of {allowed}, got {val!r}.")


# ---------------------------------------------------------------------------
# Per-file validators
# ---------------------------------------------------------------------------

def _validate_general(errors: list, warnings: list) -> None:
    path = "cfg/general_config.toml"
    cfg = _load(path, errors)
    if cfg is None:
        return

    VALID_GPU = ("cpu", "cuda", "directml", "auto", "dml", "tensorrt", "trt", "gpu", "openvino")
    _require_one_of(cfg, "cpu_or_gpu", VALID_GPU, path, errors)

    VALID_EMULATORS = ("LDPlayer", "MuMu", "BlueStacks", "Nox", "MEmu", "GameLoop")
    emu = cfg.get("current_emulator", "LDPlayer")
    if emu not in VALID_EMULATORS:
        _e(errors, f"{path}: 'current_emulator' must be one of {VALID_EMULATORS}, got {emu!r}.")

    _require_non_negative_int(cfg, "run_for_minutes", path, errors)
    _require_positive_number(cfg, "scrcpy_max_fps", path, errors)
    _require_positive_number(cfg, "scrcpy_max_width", path, errors)

    port = cfg.get("emulator_port")
    if port is not None:
        try:
            if not (1 <= int(port) <= 65535):
                _e(errors, f"{path}: 'emulator_port' must be between 1 and 65535, got {port!r}.")
        except (TypeError, ValueError):
            _e(errors, f"{path}: 'emulator_port' must be an integer port number, got {port!r}.")

    ocr = cfg.get("ocr_scale_down_factor", 0.5)
    try:
        if not (0.1 <= float(ocr) <= 1.0):
            _w(warnings, f"{path}: 'ocr_scale_down_factor' should be between 0.1 and 1.0, got {ocr!r}.")
    except (TypeError, ValueError):
        _e(errors, f"{path}: 'ocr_scale_down_factor' must be a float, got {ocr!r}.")


def _validate_bot(errors: list, warnings: list) -> None:
    path = "cfg/bot_config.toml"
    cfg = _load(path, errors)
    if cfg is None:
        return

    VALID_GAMEMODES = ("brawlball", "showdown")
    gm = cfg.get("gamemode", "")
    if str(gm).strip().lower() not in VALID_GAMEMODES:
        _e(errors, f"{path}: 'gamemode' must be one of {VALID_GAMEMODES}, got {gm!r}. The bot will not know how to play.")

    for key in ("attack_cooldown", "gadget_cooldown", "super_cooldown"):
        _require_positive_number(cfg, key, path, errors)

    _require_positive_number(cfg, "minimum_movement_delay", path, errors, allow_zero=True)

    adv = cfg.get("entity_detection_confidence")
    if adv is not None:
        try:
            v = float(adv)
            if not (0.0 < v <= 1.0):
                _e(errors, f"{path}: 'entity_detection_confidence' must be between 0 and 1, got {v!r}.")
        except (TypeError, ValueError):
            _e(errors, f"{path}: 'entity_detection_confidence' must be a float, got {adv!r}.")

    play_again = cfg.get("play_again_on_win")
    if play_again is not None and str(play_again).strip().lower() not in ("yes", "no", "true", "false", "1", "0"):
        _w(warnings, f"{path}: 'play_again_on_win' should be 'yes' or 'no', got {play_again!r}.")


def _validate_time_thresholds(errors: list, warnings: list) -> None:
    path = "cfg/time_tresholds.toml"
    cfg = _load(path, errors)
    if cfg is None:
        return

    REQUIRED_POSITIVE = (
        "state_check", "no_detections", "gadget", "hypercharge", "super",
        "wall_detection", "no_detection_proceed",
        "visual_freeze_check_interval", "visual_freeze_restart",
        "lobby_start_retry", "lobby_stuck_restart",
        "low_ips_recovery_seconds", "low_ips_recovery_cooldown",
        "post_match_transition_wait_seconds",
    )
    for key in REQUIRED_POSITIVE:
        val = cfg.get(key)
        if val is not None:
            try:
                if float(val) <= 0:
                    _e(errors, f"{path}: '{key}' must be > 0, got {val!r}.")
            except (TypeError, ValueError):
                _e(errors, f"{path}: '{key}' must be a positive number, got {val!r}.")

    restart_after = cfg.get("low_ips_app_restart_after")
    if restart_after is not None:
        try:
            if int(restart_after) < 1:
                _e(errors, f"{path}: 'low_ips_app_restart_after' must be >= 1, got {restart_after!r}.")
        except (TypeError, ValueError):
            _e(errors, f"{path}: 'low_ips_app_restart_after' must be an integer, got {restart_after!r}.")


def _validate_telegram(errors: list, warnings: list) -> None:
    path = "cfg/telegram_config.toml"
    cfg = _load(path, errors)
    if cfg is None:
        return

    telegram = cfg.get("telegram", {})
    if not isinstance(telegram, dict):
        _e(errors, f"{path}: Expected a [telegram] section, but got {type(telegram).__name__}.")
        return

    if not config_bool(telegram.get("enabled"), False):
        return  # Not enabled, skip further checks

    token = str(telegram.get("bot_token", "")).strip()
    if not token or token == "YOUR_BOT_TOKEN":
        _e(errors, (
            f"{path}: Telegram is enabled but 'bot_token' is not set. "
            "Create a bot via @BotFather and paste the token."
        ))

    chat_id = str(telegram.get("chat_id", "")).strip()
    if not chat_id or chat_id == "YOUR_CHAT_ID":
        _e(errors, (
            f"{path}: Telegram is enabled but 'chat_id' is not set. "
            "Open your bot in Telegram, send any message, then check the chat_id with @userinfobot."
        ))


def _validate_discord(errors: list, warnings: list) -> None:
    path = "cfg/discord_config.toml"
    cfg = _load(path, errors)
    if cfg is None:
        return

    if config_bool(cfg.get("discord_control_enabled"), False):
        for key, hint in (
            ("discord_bot_token", "Bot token from the Discord developer portal"),
            ("discord_control_user_id", "Your Discord user ID (right-click your name > Copy ID)"),
            ("discord_control_channel_id", "The channel ID the bot will listen in"),
            ("discord_control_guild_id", "The server (guild) ID"),
        ):
            val = str(cfg.get(key, "")).strip()
            if not val:
                _e(errors, f"{path}: Discord control is enabled but '{key}' is not set. Hint: {hint}.")

    webhook = str(cfg.get("webhook_url", "")).strip()
    if webhook and not webhook.startswith("https://discord.com/api/webhooks/"):
        _w(warnings, f"{path}: 'webhook_url' looks wrong. Expected a discord.com/api/webhooks/ URL, got: {webhook!r}.")


def _validate_models(errors: list, warnings: list) -> None:
    for name in ("mainInGameModel.onnx", "tileDetector.onnx"):
        p = os.path.join("models", name)
        if not os.path.exists(p):
            _e(errors, f"Model file missing: {p}  -- run setup.py or download models.")  # noqa


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def validate_all_configs(raise_on_error: bool = True) -> tuple[list[str], list[str]]:
    """Validate all Spectro config files.

    Prints a coloured summary to stdout.  When *raise_on_error* is True
    (default), calls sys.exit(1) if any errors were found so the user can fix
    them before the bot starts.

    Returns (errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []

    _validate_general(errors, warnings)
    _validate_bot(errors, warnings)
    _validate_time_thresholds(errors, warnings)
    _validate_telegram(errors, warnings)
    _validate_discord(errors, warnings)
    _validate_models(errors, warnings)

    # ----- pretty print -----
    RED   = "\033[91m"
    YEL   = "\033[93m"
    GRN   = "\033[92m"
    RESET = "\033[0m"

    if warnings:
        print(f"{YEL}[Config] {len(warnings)} warning(s):{RESET}")
        for w in warnings:
            print(f"  {YEL}[!]{RESET} {w}")

    if errors:
        print(f"{RED}[Config] {len(errors)} error(s) found -- please fix before starting:{RESET}")
        for err in errors:
            print(f"  {RED}[x]{RESET} {err}")
        if raise_on_error:
            sys.exit(1)
    else:
        print(f"{GRN}[Config] All config files OK ({len(warnings)} warning(s)){RESET}")

    return errors, warnings
