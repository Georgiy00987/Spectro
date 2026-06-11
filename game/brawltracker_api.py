from __future__ import annotations

import html as html_lib
import re
import ssl
import time
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import requests
from requests.adapters import HTTPAdapter

# Trophies are read from the public brawltracker.com player page.
# Only the player tag is required: no API token, developer account, or registration.

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


def clean_tag(tag):
    tag = str(tag or "").strip().upper()
    if tag.startswith("#"):
        tag = tag[1:]
    return tag


def strip_tags(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html_lib.unescape(text)
    text = re.sub(r"&amp;", "&", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


class _TLS12HttpAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        ctx = ssl.create_default_context()
        if hasattr(ssl, "TLSVersion"):
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        pool_kwargs["ssl_context"] = ctx
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


def _requests_get(url, timeout, mode):
    session = requests.Session()
    verify = True
    if mode == "tls12":
        session.mount("https://", _TLS12HttpAdapter())
    elif mode == "noverify":
        verify = False
    response = session.get(url, headers=HEADERS, timeout=timeout, verify=verify)
    response.raise_for_status()
    return response.text


def _urllib_get(url, timeout):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def _build_brawltracker_url(tag, current_trophies=None):
    url = "https://brawltracker.com/stats/player/" + quote(tag)
    params = {}
    if current_trophies not in (None, ""):
        try:
            params["current_trophies"] = int(current_trophies)
        except (TypeError, ValueError):
            params["current_trophies"] = str(current_trophies)
    if params:
        params["_ts"] = int(time.time())
        url += "?" + urlencode(params)
    return url


def fetch_html(tag, timeout=15, current_trophies=None):
    tag = clean_tag(tag)
    if not tag or tag == "YOURTAG":
        raise ValueError(
            "Player tag is empty. Set player_tag in cfg/brawl_stars_api.toml "
            "or in the Overview tab (Game ID)."
        )
    url = _build_brawltracker_url(tag, current_trophies=current_trophies)
    errors = []
    attempts = [
        ("requests", lambda: _requests_get(url, timeout, "default")),
        ("requests_tls12", lambda: _requests_get(url, timeout, "tls12")),
        ("requests_noverify", lambda: _requests_get(url, timeout, "noverify")),
        ("urllib", lambda: _urllib_get(url, timeout)),
    ]
    for name, getter in attempts:
        try:
            page_html = getter()
            if page_html:
                return page_html
        except Exception as exc:
            errors.append(name + ": " + type(exc).__name__ + ": " + str(exc))
            time.sleep(0.3)
    raise RuntimeError("Brawltracker request failed:\n" + "\n".join(errors))


def parse_brawltracker_html(page_html, tag):
    player_name = "Player"
    m = re.search(r'<h2[^>]*text-yellow-400[^>]*>(.*?)</h2>', page_html, re.I | re.S)
    if m:
        player_name = strip_tags(m.group(1)) or player_name

    brawlers = []
    img_re = re.compile(
        r'<img\s+alt="([^"]+)"[^>]+(?:brawlers%2Fportraits%2F|brawlers/portraits/)[^>]*>',
        re.I | re.S,
    )
    matches = list(img_re.finditer(page_html))
    for index, match in enumerate(matches):
        name = strip_tags(match.group(1))
        start = match.start()
        if index + 1 < len(matches):
            end = matches[index + 1].start()
        else:
            end = min(len(page_html), start + 12000)
        card = page_html[start:end]
        trophy_match = re.search(r'alt="Trophy".*?<span[^>]*>(\d+)</span>', card, re.I | re.S)
        power_match = re.search(r'alt="Power\s+(\d+)"', card, re.I | re.S)
        if trophy_match is None:
            continue
        brawlers.append({
            "name": name,
            "trophies": int(trophy_match.group(1)),
            "power": int(power_match.group(1)) if power_match else 0,
        })

    return {
        "player": player_name,
        "tag": "#" + clean_tag(tag),
        "brawlers": brawlers,
        "source": "brawltracker",
    }


def fetch_player_brawlers(player_tag, timeout=15, current_trophies=None):
    """Fetch a player's brawler trophies from brawltracker.com using only the player tag."""
    page_html = fetch_html(player_tag, timeout=timeout, current_trophies=current_trophies)
    return parse_brawltracker_html(page_html, player_tag)