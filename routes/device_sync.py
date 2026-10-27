from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models.device_sync import DeviceSync, DeviceSyncInput, DeviceSyncPutResponse, DeviceSyncSong, DeviceSyncState
from models.user import User
from utils.auth import get_current_user
from utils.time_utils import as_utc, now_utc

router = APIRouter(prefix="/device-sync", tags=["Device sync"])

# A "playing" song stays playing this long past its end, so devices can advance on their own first
END_GRACE_MS = 15_000
# With no known duration, a playing state older than this is treated as stopped
NO_DURATION_MAX_AGE_MS = 30 * 60 * 1000
# Re-sends within this of the extrapolated position are not a new event
SAME_POSITION_MS = 1500


def _duration_ms(row: DeviceSync) -> Optional[int]:
    try:
        seconds = int(str(row.duration or "").strip())
    except ValueError:
        return None
    return seconds * 1000 if seconds > 0 else None


def current_state(row: Optional[DeviceSync], now: datetime) -> DeviceSyncState:
    """The shared playback state as of `now`. A song nobody has touched since it ended reads as stopped."""
    if row is None or not row.song_id:
        return DeviceSyncState(seq=row.seq if row is not None else 0, server_time=now)

    position = row.position_ms or 0
    playing = bool(row.is_playing)
    if playing and row.position_at is not None:
        elapsed = int((now - as_utc(row.position_at)).total_seconds() * 1000)
        position += max(elapsed, 0)
        duration = _duration_ms(row)
        if duration is not None:
            if position > duration + END_GRACE_MS:
                playing, position = False, duration
            else:
                position = min(position, duration)
        elif elapsed > NO_DURATION_MAX_AGE_MS:
            playing = False

    return DeviceSyncState(
        seq=row.seq or 0,
        song=DeviceSyncSong(
            song_id=row.song_id,
            perma_url=row.perma_url,
            title=row.title or "Unknown Song",
            artist=row.artist,
            album=row.album,
            image_url=row.image_url,
            duration=row.duration,
            language=row.language,
            year=row.year,
        ),
        is_playing=playing,
        position_ms=position,
        server_time=now,
        updated_by_device_id=row.updated_by,
        updated_at=row.updated_at,
    )


@router.get("/state", response_model=DeviceSyncState)
def get_state(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """What this account is playing right now. Devices with sync on poll it (~2s)."""
    row = db.query(DeviceSync).filter(DeviceSync.user_id == current_user.id).first()
    return current_state(row, now_utc())


def _write(row: DeviceSync, payload: DeviceSyncInput, now: datetime) -> None:
    row.seq = (row.seq or 0) + 1
    row.song_id = payload.song_id
    row.perma_url = payload.perma_url
    row.title = payload.title
    row.artist = payload.artist
    row.album = payload.album
    row.image_url = payload.image_url
    row.duration = None if payload.duration is None else str(payload.duration)
    row.language = payload.language
    row.year = payload.year
    row.is_playing = payload.is_playing
    row.position_ms = payload.position_ms
    row.position_at = now
    row.updated_by = payload.device_id
    row.updated_at = now


def _is_noop(row: DeviceSync, payload: DeviceSyncInput, state: DeviceSyncState) -> bool:
    if payload.auto or row.song_id != payload.song_id:
        return False
    return state.is_playing == payload.is_playing and abs(state.position_ms - payload.position_ms) <= SAME_POSITION_MS


@router.put("/state", response_model=DeviceSyncPutResponse)
def put_state(
    payload: DeviceSyncInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A device reports a song change, pause/resume or seek. The latest report wins.
    `auto: true` + a stale `expected_seq` is ignored, so devices finishing a song together agree on one next song."""
    now = now_utc()
    row = db.query(DeviceSync).filter(DeviceSync.user_id == current_user.id).first()
    if row is None:
        row = DeviceSync(user_id=current_user.id, seq=0, is_playing=False, position_ms=0)
        db.add(row)

    state = current_state(row, now)
    if payload.auto and payload.expected_seq is not None and payload.expected_seq != (row.seq or 0):
        db.rollback()
        return DeviceSyncPutResponse(applied=False, state=state)
    if row.song_id and _is_noop(row, payload, state):
        db.rollback()
        return DeviceSyncPutResponse(applied=False, state=state)

    _write(row, payload, now)
    try:
        db.commit()
    except IntegrityError:
        # Two first-ever reports raced: the other created the row, so write onto it
        db.rollback()
        row = db.query(DeviceSync).filter(DeviceSync.user_id == current_user.id).first()
        if row is None:
            raise
        _write(row, payload, now)
        db.commit()

    return DeviceSyncPutResponse(applied=True, state=current_state(row, now))
