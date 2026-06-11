from __future__ import annotations

import html as html_lib
import json
import re
import ssl
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import requests
from requests.adapters import HTTPAdapter

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    tomllib = None

ROOT = Path(__file__).resolve().parent.parent
CFG_PATH = ROOT / "cfg" / "brawl_stars_api.toml"
ICONS2_DIR = ROOT / "api" / "assets" / "brawler_icons2"
CACHE_PATH = ROOT / "cfg" / "player_brawlers_cache.json"
LOGS_DIR = ROOT / "logs"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    "Cache-Control": "no-cache",
    "Connection": "close",
}


def log(message: str) -> None:
    print(f"[SYNCBRAWLERS2API] {message}")


def load_toml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    if tomllib is not None:
        with path.open("rb") as f:
            return dict(tomllib.load(f))
    data: Dict[str, Any] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if value.lower() in ("true", "false"):
            data[key] = value.lower() == "true"
        else:
            try:
                data[key] = int(value)
            except ValueError:
                data[key] = value
    return data


def clean_tag(tag: str) -> str:
    tag = str(tag or "").strip().upper()
    if tag.startswith("#"):
        tag = tag[1:]
    return tag


def norm_name(value: str) -> str:
    value = html_lib.unescape(str(value or ""))
    value = value.lower()
    value = value.replace("&amp;", "&")
    value = value.replace("and", "&") if value.strip() in {"larry and lawrie"} else value
    value = value.replace(".", "")
    value = value.replace("-", "")
    value = value.replace("_", "")
    value = value.replace("&", "")
    value = re.sub(r"[^a-z0-9]+", "", value)
    aliases = {
        "8bit": "8bit",
        "eightbit": "8bit",
        "larrylawrie": "larrylawrie",
        "larryandlawrie": "larrylawrie",
        "mrp": "mrp",
        "misterp": "mrp",
        "rt": "rt",
    }
    return aliases.get(value, value)


class TLS12HttpAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        ctx = ssl.create_default_context()
        if hasattr(ssl, "TLSVersion"):
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        pool_kwargs["ssl_context"] = ctx
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


def _requests_get(url: str, timeout: int, mode: str) -> str:
    session = requests.Session()
    verify = True
    if mode == "tls12":
        session.mount("https://", TLS12HttpAdapter())
    elif mode == "noverify":
        verify = False
    response = session.get(url, headers=HEADERS, timeout=timeout, verify=verify)
    log(f"request mode={mode} status={response.status_code} bytes={len(response.text)}")
    response.raise_for_status()
    return response.text


def _urllib_get(url: str, timeout: int) -> str:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
        raw = resp.read()
    text = raw.decode("utf-8", errors="replace")
    log(f"request mode=urllib bytes={len(text)}")
    return text


def _curl_get(url: str, timeout: int) -> str:
    cmd = [
        "curl", "-L", "--http1.1", "--tlsv1.2",
        "--connect-timeout", str(timeout), "--max-time", str(timeout + 5),
        "-A", HEADERS["User-Agent"],
        "-H", f"Accept: {HEADERS['Accept']}",
        "-H", f"Accept-Language: {HEADERS['Accept-Language']}",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or f"curl exit code {result.returncode}").strip())
    log(f"request mode=curl bytes={len(result.stdout)}")
    return result.stdout


def build_brawltracker_url(tag: str, current_trophies: Optional[int] = None) -> str:
    url = f"https://brawltracker.com/stats/player/{quote(tag)}"
    params: Dict[str, Any] = {}
    if current_trophies not in (None, ""):
        try:
            params["current_trophies"] = int(current_trophies)
        except (TypeError, ValueError):
            params["current_trophies"] = str(current_trophies)
    if params:
        params["_ts"] = int(time.time())
        url += "?" + urlencode(params)
    return url


def fetch_html(tag: str, timeout: int = 15, current_trophies: Optional[int] = None) -> str:
    tag = clean_tag(tag)
    if not tag or tag == "YOURTAG":
        raise ValueError("Player tag is empty. Set player_tag in cfg/brawl_stars_api.toml.")
    url = build_brawltracker_url(tag, current_trophies=current_trophies)
    log(f"loading {url}")
    errors: List[str] = []
    attempts = [
        ("requests", lambda: _requests_get(url, timeout, "default")),
        ("requests_tls12", lambda: _requests_get(url, timeout, "tls12")),
        ("requests_noverify", lambda: _requests_get(url, timeout, "noverify")),
        ("urllib", lambda: _urllib_get(url, timeout)),
        ("curl", lambda: _curl_get(url, timeout)),
    ]
    for name, getter in attempts:
        try:
            html = getter()
            if html:
                LOGS_DIR.mkdir(exist_ok=True)
                (LOGS_DIR / "debug_brawltracker_syncbrawlers2api.html").write_text(html, encoding="utf-8")
                return html
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            log(f"WARN {errors[-1]}")
            time.sleep(0.3)
    raise RuntimeError("Brawltracker request failed:\n" + "\n".join(errors))


def strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html_lib.unescape(text)
    text = re.sub(r"&amp;", "&", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def parse_brawltracker_html(html: str, tag: str) -> Dict[str, Any]:
    player_name = "Player"
    m = re.search(r'<h2[^>]*text-yellow-400[^>]*>(.*?)</h2>', html, re.I | re.S)
    if m:
        player_name = strip_tags(m.group(1)) or player_name

    brawlers: List[Dict[str, Any]] = []
    img_re = re.compile(
        r'<img\s+alt="([^"]+)"[^>]+(?:brawlers%2Fportraits%2F|brawlers/portraits/)[^>]*>',
        re.I | re.S,
    )
    matches = list(img_re.finditer(html))
    for index, match in enumerate(matches):
        name = strip_tags(match.group(1))
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(html), start + 12000)
        card = html[start:end]
        trophy_match = re.search(r'alt="Trophy".*?<span[^>]*>(\d+)</span>', card, re.I | re.S)
        power_match = re.search(r'alt="Power\s+(\d+)"', card, re.I | re.S)
        if trophy_match is None:
            continue
        brawlers.append({
            "name": name.title().replace("8 Bit", "8-Bit"),
            "trophies": int(trophy_match.group(1)),
            "power": int(power_match.group(1)) if power_match else 0,
        })

    unique: Dict[str, Dict[str, Any]] = {}
    for b in brawlers:
        unique[norm_name(b["name"])] = b
    return {"player": player_name, "tag": f"#{clean_tag(tag)}", "brawlers": list(unique.values()), "source": "brawltracker"}