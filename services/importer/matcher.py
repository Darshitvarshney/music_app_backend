import re
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from typing import Dict, List, Optional
from urllib.parse import quote

from services.jiosaavn import client as jiosaavn
from services.jiosaavn.helper import format as unescape

SEARCH_COUNT = 6
MIN_SCORE = 0.62
MIN_TITLE_RATIO = 0.6
MAX_WORKERS = 8

_SIDE_NOTE = re.compile(r"[\(\[]\s*(from|feat|ft|with)\b[^\)\]]*[\)\]]", re.I)
_SEPARATORS = re.compile(r"\s+[|\-–—]\s+")


def _norm(text: Optional[str]) -> str:
    text = _SIDE_NOTE.sub(" ", unescape(text or "").lower())
    text = re.sub(r"[^\w\s]|_", " ", text)
    return " ".join(text.split())


def _score(title: str, artist: Optional[str], candidate: dict) -> float:
    query = _norm(title)
    found = _norm(candidate.get("song"))
    found_artists = _norm(f'{candidate.get("primary_artists", "")} {candidate.get("singers", "")}')
    ratio = SequenceMatcher(None, query, found).ratio()

    if artist:
        wanted = set(_norm(artist).split())
        hit = len(wanted & set(found_artists.split())) / len(wanted) if wanted else 0
        return 0.65 * ratio + 0.35 * hit if ratio >= MIN_TITLE_RATIO else 0

    # No clean artist: the title may be "Artist - Song", so words can come from either side
    words = set(query.split())
    pool = set(found.split()) | set(found_artists.split())
    covered = len(words & pool) / len(words) if words else 0
    return 0.5 * ratio + 0.5 * covered


def _search(query: str) -> List[dict]:
    return jiosaavn.search_for_song(quote(query, safe=""), False, False, 1, SEARCH_COUNT) or []


def _best(title: str, artist: Optional[str]) -> Optional[dict]:
    text = _SEPARATORS.sub(" ", title)
    for query in dict.fromkeys([f"{text} {artist or ''}".strip(), text]):
        scored = [(_score(title, artist, c), c) for c in _search(query)]
        scored = [pair for pair in scored if pair[0] >= MIN_SCORE]
        if scored:
            return max(scored, key=lambda pair: pair[0])[1]
    return None


def _to_song(raw: dict) -> Dict[str, Optional[str]]:
    image = raw.get("image") or None
    return {
        "song_id": raw["id"],
        "perma_url": raw.get("perma_url") or "",
        "title": unescape(raw.get("song")),
        "artist": unescape(raw.get("primary_artists") or raw.get("singers")) or None,
        "album": unescape(raw.get("album")) or None,
        "image_url": image.replace("150x150", "500x500") if image else None,
        "duration": raw.get("duration"),
        "language": raw.get("language"),
        "year": raw.get("year"),
    }


def _match_one(track: dict) -> Optional[dict]:
    try:
        raw = _best(track["title"], track.get("artist"))
        return _to_song(raw) if raw else None
    except Exception:
        return None


def match_tracks(tracks: List[dict]) -> List[Optional[dict]]:
    """JioSaavn song (playlist-song shape) per track, in order; None where nothing matched."""
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        return list(pool.map(_match_one, tracks))
