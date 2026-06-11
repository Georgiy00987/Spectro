from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "cfg" / "update_config.toml"
DEFAULT_EXCLUDES = {
    ".git",
    ".idea",
    ".venv",
    "__pycache__",
    "logs",
    "runs",
    "debug_frames",
    "cfg/latest_brawler_data.json",
    "cfg/update_config.toml",
    "cfg/brawl_stars_api.toml",
    "cfg/discord_config.toml",
}


def load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    if tomllib is not None:
        with path.open("rb") as f:
            return tomllib.load(f)
    # Small fallback for this simple config format.
    data = {}
    section = data
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = data.setdefault(line[1:-1].strip(), {})
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"')
        if value.lower() in ("true", "false"):
            value = value.lower() == "true"
        section[key] = value
    return data


def parse_version(value: str) -> tuple:
    value = str(value or "0").strip().lstrip("vV")
    parts = []
    for chunk in value.replace("-", ".").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts or [0])


def is_newer(remote: str, local: str) -> bool:
    r = parse_version(remote)
    l = parse_version(local)
    size = max(len(r), len(l))
    r += (0,) * (size - len(r))
    l += (0,) * (size - len(l))
    return r > l


def request_text(url: str, token: str = "", timeout: int = 30) -> str:
    headers = {"User-Agent": "Spectro-Updater"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace").strip()


def download_file(url: str, dest: Path, token: str = "", timeout: int = 120) -> None:
    headers = {"User-Agent": "Spectro-Updater"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as response, dest.open("wb") as f:
        shutil.copyfileobj(response, f)


def get_local_version(version_file: str) -> str:
    version_path = PROJECT_ROOT / version_file
    if version_path.exists():
        return version_path.read_text(encoding="utf-8", errors="ignore").strip()
    general = load_toml(PROJECT_ROOT / "cfg" / "general_config.toml")
    return str(general.get("spectro_version", "0.0.0"))


def github_raw_url(repo: str, branch: str, version_file: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{version_file}"


def github_zip_url(repo: str, branch: str) -> str:
    return f"https://github.com/{repo}/archive/refs/heads/{branch}.zip"


def should_skip(relative_path: Path) -> bool:
    normalized = relative_path.as_posix()
    if normalized in DEFAULT_EXCLUDES:
        return True
    return any(part in DEFAULT_EXCLUDES for part in relative_path.parts)


def copy_update_tree(source_root: Path) -> None:
    for src in source_root.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(source_root)
        if should_skip(rel):
            continue
        dst = PROJECT_ROOT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def make_backup() -> Path:
    backup_root = PROJECT_ROOT.parent / f"Spectro_backup_{time.strftime('%Y%m%d_%H%M%S')}"
    def ignore(_dir, names):
        return {name for name in names if name in {".venv", "__pycache__", "logs", "runs", ".git"}}
    shutil.copytree(PROJECT_ROOT, backup_root, ignore=ignore)
    return backup_root


def find_archive_root(extract_dir: Path) -> Path:
    dirs = [p for p in extract_dir.iterdir() if p.is_dir()]
    if len(dirs) == 1:
        return dirs[0]
    return extract_dir


def run_check(config: dict) -> tuple[str, str, bool]:
    section = config.get("github_update", config)
    repo = str(section.get("repo", "")).strip()
    branch = str(section.get("branch", "main")).strip() or "main"
    version_file = str(section.get("version_file", "version")).strip() or "version"
    token = str(section.get("token", "")).strip()
    if not repo or "/" not in repo:
        raise SystemExit("Set [github_update].repo in cfg/update_config.toml, example: repo = \"owner/Spectro\"")
    local_version = get_local_version(version_file)
    remote_version = request_text(github_raw_url(repo, branch, version_file), token=token)
    return local_version, remote_version, is_newer(remote_version, local_version)


def update_project(config: dict, dry_run: bool = False) -> None:
    section = config.get("github_update", config)
    repo = str(section.get("repo", "")).strip()
    branch = str(section.get("branch", "main")).strip() or "main"
    version_file = str(section.get("version_file", "version")).strip() or "version"
    token = str(section.get("token", "")).strip()
    backup_enabled = bool(section.get("backup", True))

    local_version, remote_version, newer = run_check(config)
    print(f"Local version:  {local_version}")
    print(f"Remote version: {remote_version}")
    if not newer:
        print("Spectro is already up to date.")
        return
    if dry_run:
        print("Update is available, dry-run mode did not modify files.")
        return

    backup_path = None
    if backup_enabled:
        backup_path = make_backup()
        print(f"Backup created: {backup_path}")

    with tempfile.TemporaryDirectory(prefix="spectro_update_") as tmp:
        tmp_path = Path(tmp)
        archive_path = tmp_path / "update.zip"
        print("Downloading update archive...")
        download_file(github_zip_url(repo, branch), archive_path, token=token)
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(extract_dir)
        source_root = find_archive_root(extract_dir)
        if not (source_root / version_file).exists():
            raise RuntimeError("Downloaded archive does not contain the configured version file.")
        print("Copying files...")
        copy_update_tree(source_root)

    print(f"Updated Spectro to {remote_version}.")
    if backup_path:
        print(f"If something breaks, restore from: {backup_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Update Spectro from a GitHub repository using a version file.")
    parser.add_argument("--check", action="store_true", help="Only check remote version.")
    parser.add_argument("--dry-run", action="store_true", help="Show whether update is available without changing files.")
    args = parser.parse_args()

    config = load_toml(CONFIG_PATH)
    if args.check:
        local, remote, newer = run_check(config)
        print(f"Local version:  {local}")
        print(f"Remote version: {remote}")
        print("Update available." if newer else "Already up to date.")
        return
    update_project(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
