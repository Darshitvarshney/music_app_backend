from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models.presence import NowPlaying, NowPlayingInput, PresenceActionResponse, UserPresence
from models.user import User
from utils.auth import get_current_user
from utils.time_utils import as_utc, now_utc

router = APIRouter(prefix="/presence", tags=["Presence"])


# A heartbeat arriving sooner than this after the last one is acknowledged without a database write.
HEARTBEAT_MIN_WRITE_INTERVAL = timedelta(seconds=30)


def touch_last_seen(db: Session, user_id: str) -> None:
    """Marks the user as active now. Joins the caller's transaction; the caller commits."""
    now = now_utc()
    row = db.query(UserPresence).filter(UserPresence.user_id == user_id).first()
    if row is None:
        db.add(UserPresence(user_id=user_id, last_seen_at=now))
    elif now - as_utc(row.last_seen_at) >= HEARTBEAT_MIN_WRITE_INTERVAL:
        row.last_seen_at = now


def _apply(row: NowPlaying, payload: NowPlayingInput) -> None:
    row.song_id = payload.song_id
    row.title = payload.title
    row.artist = payload.artist
    row.album = payload.album
    row.image_url = payload.image_url
    row.perma_url = payload.perma_url
    row.is_playing = payload.is_playing
    row.updated_at = now_utc()


@router.put("/now-playing", response_model=PresenceActionResponse)
def set_now_playing(
    payload: NowPlayingInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reports what the user is playing: on song/pause/resume plus a ~3 min keep-alive.
    Friends see it as "recent" after 5 min without an update."""
    row = db.query(NowPlaying).filter(NowPlaying.user_id == current_user.id).first()
    if row is None:
        row = NowPlaying(user_id=current_user.id)
        db.add(row)
    _apply(row, payload)
    touch_last_seen(db, current_user.id)

    try:
        db.commit()
    except IntegrityError:
        # Two first-time updates raced: the other one created the row, so update it instead
        db.rollback()
        row = db.query(NowPlaying).filter(NowPlaying.user_id == current_user.id).first()
        if row is None:
            raise
        _apply(row, payload)
        touch_last_seen(db, current_user.id)
        db.commit()

    return PresenceActionResponse(message="Now playing updated")


@router.post("/heartbeat", response_model=PresenceActionResponse)
def heartbeat(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Online ping for the green circle (on open, then ~3 min in the foreground).
    Pings under 30s apart skip the DB write."""
    touch_last_seen(db, current_user.id)
    try:
        db.commit()
    except IntegrityError:
        # First-ever heartbeats raced; the other request already recorded it
        db.rollback()
    return PresenceActionResponse(message="Heartbeat recorded")


@router.delete("/now-playing", response_model=PresenceActionResponse)
def clear_now_playing(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Clears the user's now-playing info (e.g. on logout or when they want to disappear). Safe to repeat."""
    db.query(NowPlaying).filter(NowPlaying.user_id == current_user.id).delete(synchronize_session=False)
    db.commit()
    return PresenceActionResponse(message="Now playing cleared")
