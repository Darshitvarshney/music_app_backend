from typing import List, Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field

from models.playlist import PlaylistSongCreate
from models.user import User
from services.importer import matcher, spotify, tracklist, youtube
from utils.api_error import api_error
from utils.auth import get_current_user

router = APIRouter(prefix="/import", tags=["Import"])

MAX_MATCH_BATCH = 10


class ImportTrack(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    artist: Optional[str] = Field(None, max_length=200)


class SourcePageResponse(BaseModel):
    playlist_id: str
    title: Optional[str] = None
    total: int
    tracks: List[ImportTrack]
    next_page_token: Optional[str] = None


class FileImportRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1_000_000)


class MyPlaylist(BaseModel):
    id: str
    title: str
    count: int = 0


class MyPlaylistsResponse(BaseModel):
    items: List[MyPlaylist]
    next_page_token: Optional[str] = None


class MatchRequest(BaseModel):
    tracks: List[ImportTrack] = Field(..., min_length=1, max_length=MAX_MATCH_BATCH)


class MatchResult(BaseModel):
    matched: bool
    song: Optional[PlaylistSongCreate] = None


class MatchResponse(BaseModel):
    results: List[MatchResult]


@router.get("/youtube", response_model=SourcePageResponse)
def youtube_playlist(
    url: str = Query(..., max_length=300),
    page_token: Optional[str] = Query(None, max_length=200),
    google_token: Optional[str] = Header(None, alias="X-Google-Token", max_length=4096),
    current_user: User = Depends(get_current_user),
):
    """One page (50) of a YouTube / YouTube Music playlist; private ones need the user's Google token."""
    playlist_id = youtube.playlist_id_from(url)
    if not playlist_id:
        raise api_error(422, "invalid_link", "That does not look like a YouTube playlist link")
    title, tracks, next_token, total = youtube.fetch_page(playlist_id, page_token, google_token or None)
    return SourcePageResponse(
        playlist_id=playlist_id, title=title, total=total, tracks=tracks, next_page_token=next_token
    )


@router.get("/spotify", response_model=SourcePageResponse)
def spotify_playlist(
    url: str = Query(..., max_length=300),
    current_user: User = Depends(get_current_user),
):
    """A Spotify playlist anyone can open, read without a Spotify login."""
    playlist_id = spotify.playlist_id_from(url)
    if not playlist_id:
        raise api_error(422, "invalid_link", "That does not look like a Spotify playlist link")
    title, tracks = spotify.fetch_playlist(playlist_id)
    return SourcePageResponse(playlist_id=playlist_id, title=title, total=len(tracks), tracks=tracks)


@router.post("/file", response_model=SourcePageResponse)
def file_playlist(payload: FileImportRequest, current_user: User = Depends(get_current_user)):
    """Songs from the text of an exported playlist file (CSV or one song per line)."""
    tracks = tracklist.parse(payload.text)
    if not tracks:
        raise api_error(422, "no_songs_found", "No songs found in that file")
    return SourcePageResponse(playlist_id="file", total=len(tracks), tracks=tracks)


@router.get("/youtube/playlists", response_model=MyPlaylistsResponse)
def my_youtube_playlists(
    page_token: Optional[str] = Query(None, max_length=200),
    google_token: Optional[str] = Header(None, alias="X-Google-Token", max_length=4096),
    current_user: User = Depends(get_current_user),
):
    """The user's own YouTube playlists, read with their Google token (never stored)."""
    if not google_token:
        raise api_error(401, "google_token_required", "Sign in with Google first")
    items, next_token = youtube.list_my_playlists(google_token, page_token)
    return MyPlaylistsResponse(items=items, next_page_token=next_token)


@router.post("/match", response_model=MatchResponse)
def match_songs(payload: MatchRequest, current_user: User = Depends(get_current_user)):
    """Finds each track in the JioSaavn catalog; results line up with the request order."""
    songs = matcher.match_tracks([t.model_dump() for t in payload.tracks])
    return MatchResponse(
        results=[
            MatchResult(matched=song is not None, song=PlaylistSongCreate(**song) if song else None)
            for song in songs
        ]
    )
