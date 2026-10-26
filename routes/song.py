"""JioSaavn catalog routes (merged from song_api; paths and bodies unchanged)."""
import json
from traceback import print_exc

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services.jiosaavn import client as jiosaavn

router = APIRouter(tags=["Songs"])


class FlaskStyleJSONResponse(JSONResponse):
    """Flask-style JSON: ASCII-escaped, key-sorted. The Flutter client decodes as latin-1
    without a charset, so non-ASCII titles must stay escaped."""

    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")


def jsonify(content) -> FlaskStyleJSONResponse:
    return FlaskStyleJSONResponse(content)


def _int_arg(request: Request, key: str, default: int) -> int:
    """Mirrors Flask's request.args.get(key, default, type=int): bad values fall back to default."""
    try:
        return int(request.query_params[key])
    except (KeyError, ValueError):
        return default


def _lyrics_flag(request: Request) -> bool:
    lyrics_ = request.query_params.get("lyrics")
    return bool(lyrics_ and lyrics_.lower() != "false")


@router.get("/song/")
def search(request: Request):
    query = request.query_params.get("query")
    lyrics = _lyrics_flag(request)
    songdata_ = request.query_params.get("songdata")
    songdata = not (songdata_ and songdata_.lower() != "true")
    page = _int_arg(request, "page", 1)
    count = _int_arg(request, "count", _int_arg(request, "n", 20))
    if query:
        return jsonify(jiosaavn.search_for_song(query, lyrics, songdata, page, count))
    return jsonify({"status": False, "error": "Query is required to search songs!"})


@router.get("/song/get/")
def get_song(request: Request):
    id = request.query_params.get("id")
    lyrics = _lyrics_flag(request)
    if id:
        resp = jiosaavn.get_song(id, lyrics)
        if not resp:
            return jsonify({"status": False, "error": "Invalid Song ID received!"})
        return jsonify(resp)
    return jsonify({"status": False, "error": "Song ID is required to get a song!"})


@router.get("/playlist/")
def playlist(request: Request):
    query = request.query_params.get("query")
    lyrics = _lyrics_flag(request)
    if query:
        id = jiosaavn.get_playlist_id(query)
        songs = jiosaavn.get_playlist(id, lyrics)
        return jsonify(songs)
    return jsonify({"status": False, "error": "Query is required to search playlists!"})


@router.get("/album/")
def album(request: Request):
    query = request.query_params.get("query")
    lyrics = _lyrics_flag(request)
    if query:
        id = jiosaavn.get_album_id(query)
        songs = jiosaavn.get_album(id, lyrics)
        return jsonify(songs)
    return jsonify({"status": False, "error": "Query is required to search albums!"})


@router.get("/lyrics/")
def lyrics(request: Request):
    query = request.query_params.get("query")
    if query:
        try:
            if "http" in query and "saavn" in query:
                id = jiosaavn.get_song_id(query)
                lyrics = jiosaavn.get_lyrics(id)
            else:
                lyrics = jiosaavn.get_lyrics(query)
            return jsonify({"status": True, "lyrics": lyrics})
        except Exception as e:
            return jsonify({"status": False, "error": str(e)})
    return jsonify({"status": False, "error": "Query containing song link or id is required to fetch lyrics!"})


@router.get("/result/")
def result(request: Request):
    query = request.query_params.get("query")
    lyrics = _lyrics_flag(request)
    page = _int_arg(request, "page", 1)
    count = _int_arg(request, "count", _int_arg(request, "n", 20))

    if not query:
        return jsonify({"status": False, "error": "Query is required!"})

    if "saavn" not in query:
        return jsonify(jiosaavn.search_for_song(query, lyrics, True, page, count))
    try:
        if "/song/" in query:
            song_id = jiosaavn.get_song_id(query)
            song = jiosaavn.get_song(song_id, lyrics)
            return jsonify(song)

        elif "/album/" in query:
            id = jiosaavn.get_album_id(query)
            songs = jiosaavn.get_album(id, lyrics)
            return jsonify(songs)

        elif "/playlist/" in query or "/featured/" in query:
            id = jiosaavn.get_playlist_id(query)
            songs = jiosaavn.get_playlist(id, lyrics)
            return jsonify(songs)

    except Exception as e:
        print_exc()
        return jsonify({"status": False, "error": str(e)})
    return jsonify({"status": False, "error": "Invalid URL provided!"})
