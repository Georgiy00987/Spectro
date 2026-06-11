"""Version helpers for Spectro."""
from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def get_local_version(default: str = "0.0.0") -> str:
    version_path = project_root() / "version"
    try:
        value = version_path.read_text(encoding="utf-8", errors="ignore").strip()
        return value or default
    except OSError:
        return default
