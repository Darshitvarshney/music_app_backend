import csv
import io
from typing import Dict, List, Optional

MAX_TRACKS = 500

_TITLE_HEADERS = ("track name", "track", "title", "song name", "song", "name")
_ARTIST_HEADERS = ("artist name(s)", "artist names", "artist name", "artists", "artist")


def _find(header: List[str], names) -> Optional[int]:
    for name in names:
        if name in header:
            return header.index(name)
    return None


def _artist(raw: str) -> Optional[str]:
    parts = [p.strip() for p in raw.replace(" ", " ").split(";") if p.strip()]
    return " ".join(parts[:2]) or None


def _delimiter(line: str) -> str:
    return max(",;\t", key=line.count)


def parse(text: str) -> List[Dict[str, Optional[str]]]:
    """Songs from an exported CSV (Exportify, TuneMyMusic, Soundiiz...) or plain lines like "Title - Artist"."""
    lines = [line for line in text.lstrip("﻿").splitlines() if line.strip()]
    if not lines:
        return []

    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=_delimiter(lines[0])))
    header = [h.strip().lower() for h in rows[0]]
    title_col = _find(header, _TITLE_HEADERS)

    tracks: List[Dict[str, Optional[str]]] = []
    if title_col is not None:
        artist_col = _find(header, _ARTIST_HEADERS)
        for row in rows[1:]:
            title = row[title_col].strip() if title_col < len(row) else ""
            if not title:
                continue
            artist = _artist(row[artist_col]) if artist_col is not None and artist_col < len(row) else None
            tracks.append({"title": title, "artist": artist})
    else:
        tracks = [{"title": line.strip(), "artist": None} for line in lines]
    return tracks[:MAX_TRACKS]
