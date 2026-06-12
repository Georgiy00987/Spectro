"""Update settings used by the simple Updates GUI.

Creator defaults live here, but cfg/update_config.toml overrides them.
This lets you ship simple code defaults while changing update source through config.
"""
from __future__ import annotations

from pathlib import Path

import toml

# Fallback defaults, used only when cfg/update_config.toml is missing or incomplete.
DEFAULT_GITHUB_REPO = ""
DEFAULT_GITHUB_BRANCH = "main"
DEFAULT_VERSION_FILE = "version"
DEFAULT_GITHUB_TOKEN = ""
DEFAULT_CREATE_BACKUP = True

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "cfg" / "update_config.toml"


def _as_bool(value, default=True):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("yes", "true", "1", "on")


def load_update_settings():
    settings = {
        "repo": DEFAULT_GITHUB_REPO,
        "branch": DEFAULT_GITHUB_BRANCH,
        "version_file": DEFAULT_VERSION_FILE,
        "token": DEFAULT_GITHUB_TOKEN,
        "backup": DEFAULT_CREATE_BACKUP,
    }

    if CONFIG_PATH.exists():
        try:
            data = toml.load(str(CONFIG_PATH))
            section = data.get("github_update", data)
            settings["repo"] = str(section.get("repo", settings["repo"]) or "").strip()
            settings["branch"] = str(section.get("branch", settings["branch"]) or "main").strip()
            settings["version_file"] = str(section.get("version_file", settings["version_file"]) or "version").strip()
            settings["token"] = str(section.get("token", settings["token"]) or "").strip()
            settings["backup"] = _as_bool(section.get("backup", settings["backup"]), settings["backup"])
        except Exception as exc:
            print(f"Could not load update settings from {CONFIG_PATH}: {exc}")

    return settings


def as_github_update_config():
    settings = load_update_settings()
    return {"github_update": settings}


_loaded = load_update_settings()
GITHUB_REPO = _loaded["repo"]
GITHUB_BRANCH = _loaded["branch"]
VERSION_FILE = _loaded["version_file"]
GITHUB_TOKEN = _loaded["token"]
CREATE_BACKUP = _loaded["backup"]
