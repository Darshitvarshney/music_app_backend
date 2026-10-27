import os
import re
from typing import Dict, List, Optional, Tuple

import requests

from utils.api_error import api_error

API_BASE = "https://www.googleapis.com/youtube/v3"
PAGE_SIZE = 50

_LIST_PARAM = re.compile(r"[?&]list=([A-Za-z0-9_-]+)")
_BARE_ID = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
_NOISE_WORDS = r"(official|video|audio|lyrics?|lyrical|visuali[sz]er|hd|4k|mv|hq|full song)"
_BRACKET_NOISE = re.compile(r"[\(\[][^\)\]]*\b" + _NOISE_WORDS + r"\b[^\)\]]*[\)\]]", re.I)
_TAIL_NOISE = re.compile(r"\s+[|\-–—]\s*" + _NOISE_WORDS + r"\b.*$", re.I)
_UNAVAILABLE_TITLES = {"deleted video", "private video"}
_NOT_FOUND_MESSAGE = "Playlist not found. If it is private, sign in with Google to import it."


def playlist_id_from(text: str) -> Optional[str]:
    """Playlist id from a youtube.com / music.youtube.com link, or a bare id."""
    text = (text or "").strip()
    match = _LIST_PARAM.search(text)
    if match:
        return match.group(1)
    return text if _BARE_ID.match(text) else None


def clean_title(title: str) -> str:
    """Drops "(Official Video)", "[Lyrics]" and similar tags, keeps remix/live markers."""
    cleaned = _BRACKET_NOISE.sub(" ", title)
    cleaned = _TAIL_NOISE.sub("", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned or title.strip()


def parse_track(title: str, channel: Optional[str]) -> Dict[str, Optional[str]]:
    """Auto-generated "Artist - Topic" channels give a clean artist; otherwise it stays in the title."""
    artist = None
    if channel and channel.endswith(" - Topic"):
        artist = channel[: -len(" - Topic")].strip() or None
    return {"title": clean_title(title), "artist": artist}


def _get(path: str, token: Optional[str] = None, **params) -> dict:
    """Calls the YouTube API as the user when they gave a Google token, else with our API key."""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        key = os.getenv("YOUTUBE_API_KEY")
        if not key:
            raise api_error(503, "youtube_not_configured", "YouTube import is not set up on the server yet")
        params["key"] = key
    try:
        response = requests.get(f"{API_BASE}/{path}", params=params, headers=headers, timeout=8)
    except requests.RequestException:
        raise api_error(502, "youtube_unreachable", "Could not reach YouTube, please try again")

    if response.status_code == 200:
        return response.json()

    try:
        reason = response.json()["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError):
        reason = ""
    if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
        raise api_error(503, "youtube_quota", "YouTube import is busy for today, please try again tomorrow")
    if token and response.status_code == 401:
        raise api_error(401, "google_token_invalid", "Google sign-in expired, please sign in again")
    if reason == "insufficientPermissions" and token:
        raise api_error(403, "google_permission", "YouTube access was not allowed. Sign in again and tick the YouTube permission")
    if reason == "youtubeSignupRequired":
        raise api_error(404, "no_youtube_channel", "That Google account has no YouTube channel or playlists")
    if response.status_code in (403, 404) or reason in ("playlistNotFound", "playlistItemsNotAccessible"):
        raise api_error(404, "playlist_not_found", _NOT_FOUND_MESSAGE)
    raise api_error(502, "youtube_error", "YouTube returned an error, please try again")


def fetch_page(
    playlist_id: str, page_token: Optional[str], token: Optional[str] = None
) -> Tuple[Optional[str], List[dict], Optional[str], int]:
    """One page of up to 50 tracks: (title on the first page, tracks, next page token, total)."""
    title = None
    if not page_token:
        meta = _get("playlists", token, part="snippet", id=playlist_id)
        items = meta.get("items") or []
        if not items:
            raise api_error(404, "playlist_not_found", _NOT_FOUND_MESSAGE)
        title = items[0]["snippet"]["title"]

    params = {"part": "snippet", "playlistId": playlist_id, "maxResults": PAGE_SIZE}
    if page_token:
        params["pageToken"] = page_token
    data = _get("playlistItems", token, **params)

    tracks = []
    for item in data.get("items", []):
        snippet = item.get("snippet") or {}
        raw_title = snippet.get("title") or ""
        if not raw_title or raw_title.lower() in _UNAVAILABLE_TITLES:
            continue
        tracks.append(parse_track(raw_title, snippet.get("videoOwnerChannelTitle")))

    total = (data.get("pageInfo") or {}).get("totalResults", len(tracks))
    return title, tracks, data.get("nextPageToken"), total


def list_my_playlists(token: str, page_token: Optional[str]) -> Tuple[List[dict], Optional[str]]:
    """The signed-in user's own playlists (private ones included), one page of 50."""
    params = {"part": "snippet,contentDetails", "mine": "true", "maxResults": PAGE_SIZE}
    if page_token:
        params["pageToken"] = page_token
    data = _get("playlists", token, **params)
    items = [
        {
            "id": item["id"],
            "title": (item.get("snippet") or {}).get("title") or "Untitled playlist",
            "count": (item.get("contentDetails") or {}).get("itemCount", 0),
        }
        for item in data.get("items", [])
        if item.get("id")
    ]
    return items, data.get("nextPageToken")
