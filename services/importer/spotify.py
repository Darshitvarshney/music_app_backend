import json
import re
from typing import Dict, List, Optional, Tuple

import requests

from utils.api_error import api_error

EMBED_URL = "https://open.spotify.com/embed/playlist/{}"
MAX_ARTISTS = 2

_ID = re.compile(r"playlist[/:]([A-Za-z0-9]{22})")
_BARE_ID = re.compile(r"^[A-Za-z0-9]{22}$")
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_VERSION_TAIL = re.compile(r"\s+-\s+(\d{4}\s+)?(remaster(ed)?|radio edit|single version|mono|stereo|from)\b.*$", re.I)
_NOT_READABLE = "Could not read this playlist. If it is private, make it public for a minute or upload a file instead."


def playlist_id_from(text: str) -> Optional[str]:
    """Playlist id from an open.spotify.com link, a spotify: URI or a bare id."""
    text = (text or "").strip()
    match = _ID.search(text)
    if match:
        return match.group(1)
    return text if _BARE_ID.match(text) else None


def parse_track(item: dict) -> Optional[Dict[str, Optional[str]]]:
    if item.get("entityType") not in (None, "track"):
        return None
    title = _VERSION_TAIL.sub("", (item.get("title") or "").strip())
    if not title:
        return None
    artists = [a.strip() for a in (item.get("subtitle") or "").replace("\u00a0", " ").split(",") if a.strip()]
    return {"title": title, "artist": " ".join(artists[:MAX_ARTISTS]) or None}


def fetch_playlist(playlist_id: str) -> Tuple[str, List[dict]]:
    """Title and tracks of a playlist anyone can open, read from Spotify's public embed page."""
    try:
        response = requests.get(
            EMBED_URL.format(playlist_id), headers={"User-Agent": "Mozilla/5.0"}, timeout=8
        )
    except requests.RequestException:
        raise api_error(502, "spotify_unreachable", "Could not reach Spotify, please try again")
    if response.status_code != 200:
        raise api_error(502, "spotify_unreachable", "Could not reach Spotify, please try again")

    try:
        match = _NEXT_DATA.search(response.content.decode("utf-8", errors="replace"))
        entity = json.loads(match.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
        items = entity["trackList"]
    except (AttributeError, KeyError, TypeError, ValueError):
        raise api_error(404, "playlist_not_found", _NOT_READABLE)

    tracks = [t for t in (parse_track(i) for i in items) if t]
    title = entity.get("name") or entity.get("title") or "Spotify playlist"
    return title, tracks
