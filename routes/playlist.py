from datetime import datetime, timezone
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models.playlist import (
    Playlist,
    PlaylistActionResponse,
    PlaylistCreate,
    PlaylistDetail,
    PlaylistListResponse,
    PlaylistMembershipResponse,
    PlaylistSong,
    PlaylistSongActionResponse,
    PlaylistSongCreate,
    PlaylistSongResponse,
    PlaylistSummary,
    PlaylistUpdate,
)
from models.user import User
from utils.auth import get_current_user

router = APIRouter(prefix="/playlists", tags=["Playlists"])

MAX_PLAYLISTS_PER_USER = 50
MAX_SONGS_PER_PLAYLIST = 500
COVER_IMAGE_COUNT = 4


def _clean_name(name: str) -> str:
    return " ".join(name.split())


def _name_key(name: str) -> str:
    return _clean_name(name).lower()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _owned_playlist(db: Session, user: User, playlist_id: str) -> Playlist:
    playlist = (
        db.query(Playlist)
        .filter(Playlist.id == playlist_id, Playlist.user_id == user.id)
        .first()
    )
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return playlist


def _summaries(db: Session, playlists: List[Playlist]) -> List[PlaylistSummary]:
    """Summaries (song count + cover collage) for several playlists in two queries."""
    if not playlists:
        return []
    ids = [p.id for p in playlists]

    counts: Dict[str, int] = dict(
        db.query(PlaylistSong.playlist_id, func.count(PlaylistSong.id))
        .filter(PlaylistSong.playlist_id.in_(ids))
        .group_by(PlaylistSong.playlist_id)
        .all()
    )

    rank = (
        func.row_number()
        .over(partition_by=PlaylistSong.playlist_id, order_by=(PlaylistSong.position, PlaylistSong.id))
        .label("rank")
    )
    ranked = (
        db.query(PlaylistSong.playlist_id.label("pid"), PlaylistSong.image_url.label("img"), rank)
        .filter(PlaylistSong.playlist_id.in_(ids), PlaylistSong.image_url.isnot(None), PlaylistSong.image_url != "")
        .subquery()
    )
    covers: Dict[str, List[str]] = {pid: [] for pid in ids}
    rows = (
        db.query(ranked.c.pid, ranked.c.img, ranked.c.rank)
        .filter(ranked.c.rank <= COVER_IMAGE_COUNT)
        .order_by(ranked.c.pid, ranked.c.rank)
        .all()
    )
    for pid, img, _ in rows:
        covers[pid].append(img)

    return [
        PlaylistSummary(
            id=p.id,
            name=p.name,
            description=p.description,
            song_count=counts.get(p.id, 0),
            cover_images=covers.get(p.id, []),
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in playlists
    ]


def _summary(db: Session, playlist: Playlist) -> PlaylistSummary:
    return _summaries(db, [playlist])[0]


def _commit_or_name_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You already have a playlist with that name")


@router.post("", response_model=PlaylistActionResponse, status_code=status.HTTP_201_CREATED)
def create_playlist(
    payload: PlaylistCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Creates an empty playlist; names are unique per user, ignoring case and spacing."""
    name = _clean_name(payload.name)
    if not name:
        raise HTTPException(status_code=422, detail="Playlist name must not be blank")

    owned = db.query(Playlist).filter(Playlist.user_id == current_user.id)
    if owned.filter(Playlist.name_key == _name_key(name)).first():
        raise HTTPException(status_code=409, detail="You already have a playlist with that name")
    if owned.count() >= MAX_PLAYLISTS_PER_USER:
        raise HTTPException(status_code=400, detail=f"You can have at most {MAX_PLAYLISTS_PER_USER} playlists")

    now = _now()
    description = (payload.description or "").strip() or None
    playlist = Playlist(
        user_id=current_user.id,
        name=name,
        name_key=_name_key(name),
        description=description,
        created_at=now,
        updated_at=now,
    )
    db.add(playlist)
    _commit_or_name_conflict(db)
    db.refresh(playlist)
    return PlaylistActionResponse(message="Playlist created", playlist=_summary(db, playlist))


@router.get("", response_model=PlaylistListResponse)
def list_playlists(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The authenticated user's playlists, most recently changed first."""
    playlists = (
        db.query(Playlist)
        .filter(Playlist.user_id == current_user.id)
        .order_by(Playlist.updated_at.desc(), Playlist.id)
        .all()
    )
    return PlaylistListResponse(items=_summaries(db, playlists))


@router.get("/by-song/{song_id}", response_model=PlaylistMembershipResponse)
def playlists_containing_song(
    song_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Playlists that already contain this song (for the add-to-playlist sheet)."""
    ids = [
        row[0]
        for row in db.query(PlaylistSong.playlist_id)
        .join(Playlist, Playlist.id == PlaylistSong.playlist_id)
        .filter(Playlist.user_id == current_user.id, PlaylistSong.song_id == song_id)
        .all()
    ]
    return PlaylistMembershipResponse(song_id=song_id, playlist_ids=ids)


@router.get("/{playlist_id}", response_model=PlaylistDetail)
def get_playlist(
    playlist_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One playlist with its songs in play order."""
    playlist = _owned_playlist(db, current_user, playlist_id)
    songs = (
        db.query(PlaylistSong)
        .filter(PlaylistSong.playlist_id == playlist.id)
        .order_by(PlaylistSong.position, PlaylistSong.id)
        .all()
    )
    summary = _summary(db, playlist)
    return PlaylistDetail(
        **summary.model_dump(),
        songs=[PlaylistSongResponse.model_validate(s) for s in songs],
    )


@router.patch("/{playlist_id}", response_model=PlaylistActionResponse)
def update_playlist(
    playlist_id: str,
    payload: PlaylistUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Renames a playlist and/or changes its description."""
    playlist = _owned_playlist(db, current_user, playlist_id)

    if payload.name is not None:
        name = _clean_name(payload.name)
        if not name:
            raise HTTPException(status_code=422, detail="Playlist name must not be blank")
        clash = (
            db.query(Playlist.id)
            .filter(
                Playlist.user_id == current_user.id,
                Playlist.name_key == _name_key(name),
                Playlist.id != playlist.id,
            )
            .first()
        )
        if clash:
            raise HTTPException(status_code=409, detail="You already have a playlist with that name")
        playlist.name = name
        playlist.name_key = _name_key(name)
    if payload.description is not None:
        playlist.description = payload.description.strip() or None

    playlist.updated_at = _now()
    _commit_or_name_conflict(db)
    db.refresh(playlist)
    return PlaylistActionResponse(message="Playlist updated", playlist=_summary(db, playlist))


@router.delete("/{playlist_id}", response_model=PlaylistActionResponse)
def delete_playlist(
    playlist_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes a playlist and its song entries (idempotent)."""
    playlist = (
        db.query(Playlist)
        .filter(Playlist.id == playlist_id, Playlist.user_id == current_user.id)
        .first()
    )
    if playlist is None:
        return PlaylistActionResponse(message="Playlist not found")
    # Delete children explicitly; SQLite ignores ON DELETE CASCADE
    db.query(PlaylistSong).filter(PlaylistSong.playlist_id == playlist.id).delete(synchronize_session=False)
    db.delete(playlist)
    db.commit()
    return PlaylistActionResponse(message="Playlist deleted")


@router.post("/{playlist_id}/songs", response_model=PlaylistSongActionResponse)
def add_song(
    playlist_id: str,
    payload: PlaylistSongCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Appends a song; adding one that is already there is a no-op."""
    playlist = _owned_playlist(db, current_user, playlist_id)

    existing = (
        db.query(PlaylistSong)
        .filter(PlaylistSong.playlist_id == playlist.id, PlaylistSong.song_id == payload.song_id)
        .first()
    )
    if existing:
        return PlaylistSongActionResponse(
            message="Song is already in this playlist", added=False, playlist=_summary(db, playlist)
        )

    count, last_position = (
        db.query(func.count(PlaylistSong.id), func.max(PlaylistSong.position))
        .filter(PlaylistSong.playlist_id == playlist.id)
        .one()
    )
    if count >= MAX_SONGS_PER_PLAYLIST:
        raise HTTPException(status_code=400, detail=f"A playlist can hold at most {MAX_SONGS_PER_PLAYLIST} songs")

    db.add(
        PlaylistSong(
            playlist_id=playlist.id,
            song_id=payload.song_id,
            perma_url=payload.perma_url,
            title=payload.title,
            artist=payload.artist,
            album=payload.album,
            image_url=payload.image_url,
            duration=str(payload.duration) if payload.duration is not None else None,
            language=payload.language,
            year=payload.year,
            position=(last_position or 0) + 1,
            added_at=_now(),
        )
    )
    playlist.updated_at = _now()
    try:
        db.commit()
    except IntegrityError:
        # Added concurrently, the other request won
        db.rollback()
        return PlaylistSongActionResponse(
            message="Song is already in this playlist", added=False, playlist=_summary(db, playlist)
        )
    db.refresh(playlist)
    return PlaylistSongActionResponse(message="Song added", added=True, playlist=_summary(db, playlist))


@router.delete("/{playlist_id}/songs/{song_id}", response_model=PlaylistSongActionResponse)
def remove_song(
    playlist_id: str,
    song_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Removes a song (idempotent); the rest keep their order."""
    playlist = _owned_playlist(db, current_user, playlist_id)
    deleted = (
        db.query(PlaylistSong)
        .filter(PlaylistSong.playlist_id == playlist.id, PlaylistSong.song_id == song_id)
        .delete(synchronize_session=False)
    )
    if deleted:
        playlist.updated_at = _now()
    db.commit()
    db.refresh(playlist)
    return PlaylistSongActionResponse(
        message="Song removed" if deleted else "Song not in this playlist",
        added=False,
        playlist=_summary(db, playlist),
    )
