from datetime import timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models.friendship import STATUS_ACCEPTED, Friendship
from models.profile import UserProfile
from models.room import (
    MAX_ROOM_MEMBERS,
    MEMBER_INVITED,
    MEMBER_JOINED,
    CurrentRoomResponse,
    Room,
    RoomActionResponse,
    RoomCreate,
    RoomInvite,
    RoomInviteItem,
    RoomMember,
    RoomMemberInfo,
    RoomSong,
    RoomSongInput,
    RoomSongResponse,
    RoomState,
)
from models.user import User
from routes.friend import require_own_username, sorted_pair
from utils.api_error import api_error
from utils.auth import get_current_user
from utils.time_utils import as_utc, now_utc
from utils.username import normalize_username

router = APIRouter(prefix="/rooms", tags=["Rooms"])

# Pending invites expire after this
INVITE_TTL = timedelta(hours=1)
# Members not seen for this long show as offline (apps poll every ~2s)
ONLINE_WINDOW = timedelta(seconds=30)
# A member silent this long counts as gone when joining another room
STALE_MEMBER_AFTER = timedelta(minutes=3)
# Skip the DB write when the last poll was more recent than this
LAST_SEEN_WRITE_INTERVAL = timedelta(seconds=10)


def _delete_room_if_empty(db: Session, room_id: str) -> None:
    joined = (
        db.query(RoomMember.id)
        .filter(RoomMember.room_id == room_id, RoomMember.status == MEMBER_JOINED)
        .first()
    )
    if joined is None:
        # Delete children explicitly; SQLite ignores ON DELETE CASCADE
        db.query(RoomMember).filter(RoomMember.room_id == room_id).delete(synchronize_session=False)
        db.query(Room).filter(Room.id == room_id).delete(synchronize_session=False)


def _purge_expired_invites(db: Session, room_id: Optional[str] = None) -> None:
    cutoff = now_utc() - INVITE_TTL
    query = db.query(RoomMember).filter(RoomMember.status == MEMBER_INVITED, RoomMember.created_at < cutoff)
    if room_id is not None:
        query = query.filter(RoomMember.room_id == room_id)
    query.delete(synchronize_session=False)


def _joined_membership(db: Session, user_id: str) -> Optional[RoomMember]:
    return (
        db.query(RoomMember)
        .filter(RoomMember.user_id == user_id, RoomMember.status == MEMBER_JOINED)
        .first()
    )


def _is_stale(member: RoomMember) -> bool:
    seen = member.last_seen_at or member.joined_at or member.created_at
    return seen is None or now_utc() - as_utc(seen) > STALE_MEMBER_AFTER


def _ensure_free_to_join(db: Session, user_id: str) -> None:
    """Raises if already in a live room; drops a stale membership."""
    existing = _joined_membership(db, user_id)
    if existing is None:
        return
    if _is_stale(existing):
        room_id = existing.room_id
        db.delete(existing)
        db.flush()
        _delete_room_if_empty(db, room_id)
        db.flush()
        return
    raise api_error(409, "already_in_room", "Leave your current room before joining another one")


def _touch(member: RoomMember) -> None:
    now = now_utc()
    if member.last_seen_at is None or now - as_utc(member.last_seen_at) >= LAST_SEEN_WRITE_INTERVAL:
        member.last_seen_at = now


def _are_friends(db: Session, a: str, b: str) -> bool:
    low, high = sorted_pair(a, b)
    return (
        db.query(Friendship.id)
        .filter(Friendship.user_low == low, Friendship.user_high == high, Friendship.status == STATUS_ACCEPTED)
        .first()
        is not None
    )


def _member_count(db: Session, room_id: str) -> int:
    return db.query(RoomMember).filter(RoomMember.room_id == room_id).count()


def _people(db: Session, user_ids: List[str]) -> Dict[str, Dict[str, str]]:
    """user_id -> {username, name} (falls back to the display name)."""
    if not user_ids:
        return {}
    users = db.query(User).filter(User.id.in_(user_ids)).all()
    profiles = {
        p.user_id: p.username
        for p in db.query(UserProfile).filter(UserProfile.user_id.in_(user_ids)).all()
    }
    return {u.id: {"username": profiles.get(u.id) or u.name, "name": u.name} for u in users}


def _state(db: Session, room: Room, me: User) -> RoomState:
    members = (
        db.query(RoomMember)
        .filter(RoomMember.room_id == room.id)
        .order_by(RoomMember.created_at, RoomMember.id)
        .all()
    )
    ids = [m.user_id for m in members] + ([room.song_changed_by] if room.song_changed_by else [])
    people = _people(db, ids)
    now = now_utc()

    infos = []
    for m in members:
        person = people.get(m.user_id, {"username": "unknown", "name": "Unknown"})
        online = (
            m.status == MEMBER_JOINED
            and m.last_seen_at is not None
            and now - as_utc(m.last_seen_at) <= ONLINE_WINDOW
        )
        infos.append(
            RoomMemberInfo(
                username=person["username"],
                name=person["name"],
                status=m.status,
                online=online or m.user_id == me.id,
                is_me=m.user_id == me.id,
            )
        )

    song = None
    if room.song_id:
        song = RoomSong(
            song_id=room.song_id,
            perma_url=room.perma_url,
            title=room.title or "Unknown Song",
            artist=room.artist,
            album=room.album,
            image_url=room.image_url,
            duration=room.duration,
            language=room.language,
            year=room.year,
        )
    changer = people.get(room.song_changed_by) if room.song_changed_by else None
    return RoomState(
        id=room.id,
        capacity=MAX_ROOM_MEMBERS,
        song_seq=room.song_seq or 0,
        song=song,
        song_changed_by=changer["username"] if changer else None,
        song_changed_at=room.song_changed_at,
        members=infos,
    )


def _joined_room(db: Session, me: User, room_id: str) -> tuple:
    """(room, membership), or 404 if the user has not joined that room."""
    member = (
        db.query(RoomMember)
        .filter(RoomMember.room_id == room_id, RoomMember.user_id == me.id, RoomMember.status == MEMBER_JOINED)
        .first()
    )
    room = db.query(Room).filter(Room.id == room_id).first() if member else None
    if member is None or room is None:
        raise api_error(404, "room_not_found", "You are not in that room")
    return room, member


def _invite_user(db: Session, room: Room, me: User, username: str) -> None:
    """Adds a pending invite; raises api_error on any rule violation."""
    key = normalize_username(username)
    profile = db.query(UserProfile).filter(UserProfile.username == key).first() if key else None
    if profile is None:
        raise api_error(404, "user_not_found", f"No user named {username}")
    if profile.user_id == me.id:
        raise api_error(400, "cannot_invite_self", "You are already in the room")
    if not _are_friends(db, me.id, profile.user_id):
        raise api_error(403, "not_friends", "You can only invite your friends")
    already = (
        db.query(RoomMember.id)
        .filter(RoomMember.room_id == room.id, RoomMember.user_id == profile.user_id)
        .first()
    )
    if already:
        raise api_error(409, "already_invited", "That friend is already in this room or invited")
    if _member_count(db, room.id) >= MAX_ROOM_MEMBERS:
        raise api_error(409, "room_full", f"A room can have at most {MAX_ROOM_MEMBERS} people")
    db.add(RoomMember(room_id=room.id, user_id=profile.user_id, invited_by=me.id, status=MEMBER_INVITED,
                      created_at=now_utc()))
    db.flush()


@router.post("", response_model=RoomActionResponse, status_code=201)
def create_room(
    payload: RoomCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Creates a room, optionally inviting up to two friends."""
    require_own_username(db, current_user)
    _ensure_free_to_join(db, current_user.id)

    usernames = []
    for u in payload.usernames:
        key = normalize_username(u)
        if key and key not in usernames:
            usernames.append(key)
    if len(usernames) > MAX_ROOM_MEMBERS - 1:
        raise api_error(400, "too_many_invites", f"A room can have at most {MAX_ROOM_MEMBERS} people")

    now = now_utc()
    room = Room(created_by=current_user.id, created_at=now)
    db.add(room)
    db.flush()
    db.add(RoomMember(room_id=room.id, user_id=current_user.id, status=MEMBER_JOINED,
                      created_at=now, joined_at=now, last_seen_at=now))
    db.flush()
    for key in usernames:
        _invite_user(db, room, current_user, key)  # raises -> whole creation is rolled back by get_db close
    db.commit()
    db.refresh(room)
    return RoomActionResponse(message="Room created", room=_state(db, room, current_user))


@router.get("/current", response_model=CurrentRoomResponse)
def current_room(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The caller's room, or their pending invites if none. Polled every ~2s, which also
    marks the member as connected."""
    membership = _joined_membership(db, current_user.id)
    if membership is not None:
        room = db.query(Room).filter(Room.id == membership.room_id).first()
        if room is not None:
            _touch(membership)
            _purge_expired_invites(db, room.id)
            db.commit()
            return CurrentRoomResponse(room=_state(db, room, current_user))

    cutoff = now_utc() - INVITE_TTL
    rows = (
        db.query(RoomMember)
        .filter(RoomMember.user_id == current_user.id, RoomMember.status == MEMBER_INVITED,
                RoomMember.created_at >= cutoff)
        .order_by(RoomMember.created_at.desc())
        .all()
    )
    people = _people(db, [r.invited_by for r in rows if r.invited_by])
    invites = []
    for r in rows:
        inviter = people.get(r.invited_by) if r.invited_by else None
        invites.append(
            RoomInviteItem(
                room_id=r.room_id,
                invited_by_username=inviter["username"] if inviter else None,
                invited_by_name=inviter["name"] if inviter else None,
                member_count=_member_count(db, r.room_id),
                created_at=r.created_at,
            )
        )
    return CurrentRoomResponse(invites=invites)


@router.post("/{room_id}/invite", response_model=RoomActionResponse)
def invite_friend(
    room_id: str,
    payload: RoomInvite,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Invites a friend. Pending invites hold a seat, so a room never exceeds 3."""
    room, member = _joined_room(db, current_user, room_id)
    _purge_expired_invites(db, room.id)
    _invite_user(db, room, current_user, payload.username)
    _touch(member)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise api_error(409, "already_invited", "That friend is already in this room or invited")
    return RoomActionResponse(message="Invite sent", room=_state(db, room, current_user))


@router.post("/{room_id}/accept", response_model=RoomActionResponse)
def accept_invite(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Joins a room the caller was invited to."""
    invite = (
        db.query(RoomMember)
        .filter(RoomMember.room_id == room_id, RoomMember.user_id == current_user.id,
                RoomMember.status == MEMBER_INVITED)
        .first()
    )
    room = db.query(Room).filter(Room.id == room_id).first() if invite else None
    if invite is None or room is None or now_utc() - as_utc(invite.created_at) > INVITE_TTL:
        raise api_error(404, "invite_not_found", "That invite is no longer available")

    _ensure_free_to_join(db, current_user.id)
    now = now_utc()
    invite.status = MEMBER_JOINED
    invite.joined_at = now
    invite.last_seen_at = now
    db.commit()
    return RoomActionResponse(message="Joined room", room=_state(db, room, current_user))


@router.post("/{room_id}/decline", response_model=RoomActionResponse)
def decline_invite(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Turns an invite down (idempotent)."""
    db.query(RoomMember).filter(
        RoomMember.room_id == room_id, RoomMember.user_id == current_user.id,
        RoomMember.status == MEMBER_INVITED,
    ).delete(synchronize_session=False)
    _delete_room_if_empty(db, room_id)
    db.commit()
    return RoomActionResponse(message="Invite declined")


@router.post("/{room_id}/leave", response_model=RoomActionResponse)
def leave_room(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Leaves the room (idempotent); it is deleted once empty."""
    db.query(RoomMember).filter(
        RoomMember.room_id == room_id, RoomMember.user_id == current_user.id,
    ).delete(synchronize_session=False)
    _delete_room_if_empty(db, room_id)
    db.commit()
    return RoomActionResponse(message="Left room")


@router.put("/{room_id}/song", response_model=RoomSongResponse)
def set_room_song(
    room_id: str,
    payload: RoomSongInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Shares a new song; others start it on their next poll (pause/seek are never sent).
    Same song is a no-op; `auto` with a stale `expected_seq` is dropped so phones agree."""
    room, member = _joined_room(db, current_user, room_id)
    _touch(member)

    if payload.song_id == room.song_id:
        db.commit()
        return RoomSongResponse(applied=False, message="That song is already playing in the room",
                                room=_state(db, room, current_user))
    if payload.auto and payload.expected_seq is not None and payload.expected_seq != (room.song_seq or 0):
        db.commit()
        return RoomSongResponse(applied=False, message="The room already moved on",
                                room=_state(db, room, current_user))

    room.song_seq = (room.song_seq or 0) + 1
    room.song_id = payload.song_id
    room.perma_url = payload.perma_url
    room.title = payload.title
    room.artist = payload.artist
    room.album = payload.album
    room.image_url = payload.image_url
    room.duration = str(payload.duration) if payload.duration is not None else None
    room.language = payload.language
    room.year = payload.year
    room.song_changed_by = current_user.id
    room.song_changed_at = now_utc()
    db.commit()
    db.refresh(room)
    return RoomSongResponse(applied=True, message="Song shared with the room",
                            room=_state(db, room, current_user))
