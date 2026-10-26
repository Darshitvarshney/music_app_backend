from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models.friendship import (
    STATUS_ACCEPTED,
    STATUS_DECLINED,
    STATUS_PENDING,
    Friendship,
    FriendListResponse,
    FriendRequestActionResponse,
    FriendRequestInput,
    FriendRequestItem,
    FriendRequestListResponse,
    FriendResponse,
)
from models.presence import (
    LIVE_WINDOW_SECONDS,
    RECENT_WINDOW_SECONDS,
    STATUS_IDLE,
    STATUS_LISTENING,
    STATUS_ONLINE,
    STATUS_PAUSED,
    STATUS_RECENT,
    FriendActivity,
    FriendActivityListResponse,
    NowPlaying,
    SongSnapshot,
    UserPresence,
)
from models.profile import UserProfile
from models.user import User
from utils.api_error import api_error
from utils.auth import get_current_user
from utils.time_utils import as_utc, now_utc
from utils.username import normalize_username

router = APIRouter(prefix="/friends", tags=["Friends"])

MAX_FRIENDS = 200
MAX_PENDING_OUTGOING_REQUESTS = 50


def sorted_pair(a: str, b: str) -> Tuple[str, str]:
    return (a, b) if a < b else (b, a)


def other_user_id(row: Friendship, me: str) -> str:
    return row.user_high if row.user_low == me else row.user_low


def require_own_username(db: Session, user: User) -> UserProfile:
    profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    if profile is None or not profile.username:
        raise api_error(403, "username_required", "Choose a username before using friends")
    return profile


def load_people(db: Session, user_ids: List[str]) -> Dict[str, Tuple[UserProfile, User]]:
    """user_id -> (profile, user) for users that have a username."""
    if not user_ids:
        return {}
    rows = (
        db.query(UserProfile, User)
        .join(User, User.id == UserProfile.user_id)
        .filter(UserProfile.user_id.in_(user_ids), UserProfile.username.isnot(None))
        .all()
    )
    return {profile.user_id: (profile, user) for profile, user in rows}


def to_friend(person: Tuple[UserProfile, User], since=None) -> FriendResponse:
    profile, user = person
    return FriendResponse(username=profile.username, name=user.name, since=since)


def accepted_rows(db: Session, me: str) -> List[Friendship]:
    return (
        db.query(Friendship)
        .filter(
            Friendship.status == STATUS_ACCEPTED,
            or_(Friendship.user_low == me, Friendship.user_high == me),
        )
        .all()
    )


@router.get("", response_model=FriendListResponse)
def list_friends(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The signed-in user's friends (accepted requests only), alphabetically."""
    rows = accepted_rows(db, current_user.id)
    people = load_people(db, [other_user_id(r, current_user.id) for r in rows])

    items = [
        to_friend(people[fid], since=row.updated_at)
        for row in rows
        for fid in [other_user_id(row, current_user.id)]
        if fid in people
    ]
    items.sort(key=lambda f: f.username)
    return FriendListResponse(total=len(items), items=items)


@router.get("/requests", response_model=FriendRequestListResponse)
def list_friend_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pending friend requests: `incoming` (waiting for you) and `outgoing` (waiting for them)."""
    me = current_user.id
    rows = (
        db.query(Friendship)
        .filter(
            Friendship.status == STATUS_PENDING,
            or_(Friendship.user_low == me, Friendship.user_high == me),
        )
        .order_by(Friendship.created_at.desc())
        .all()
    )
    people = load_people(db, [other_user_id(r, me) for r in rows])

    incoming: List[FriendRequestItem] = []
    outgoing: List[FriendRequestItem] = []
    for row in rows:
        fid = other_user_id(row, me)
        if fid not in people:
            continue
        profile, user = people[fid]
        item = FriendRequestItem(id=row.id, username=profile.username, name=user.name, created_at=row.created_at)
        (outgoing if row.requester_id == me else incoming).append(item)

    return FriendRequestListResponse(incoming=incoming, outgoing=outgoing)


@router.post("/requests", response_model=FriendRequestActionResponse)
def send_friend_request(
    payload: FriendRequestInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sends a friend request. If they already asked you it accepts; repeats are no-ops
    and a decline is never revealed to the sender."""
    me = current_user.id
    my_profile = require_own_username(db, current_user)

    target_username = normalize_username(payload.username)
    if target_username == my_profile.username:
        raise api_error(400, "cannot_add_self", "You can't add yourself")

    target_profile = db.query(UserProfile).filter(UserProfile.username == target_username).first()
    if target_profile is None:
        raise api_error(404, "user_not_found", f"No user with the username '{target_username}'")
    target = db.query(User).filter(User.id == target_profile.user_id).first()
    target_person = (target_profile, target)

    low, high = sorted_pair(me, target_profile.user_id)
    row = db.query(Friendship).filter(Friendship.user_low == low, Friendship.user_high == high).first()

    if row is not None:
        if row.status == STATUS_ACCEPTED:
            return FriendRequestActionResponse(
                message="You are already friends", status="accepted", friend=to_friend(target_person)
            )
        if row.status == STATUS_PENDING and row.requester_id == target_profile.user_id:
            return _accept(db, row, me, target_person)
        if row.status == STATUS_PENDING:
            return FriendRequestActionResponse(message="Friend request already sent", status="pending")
        # declined
        if row.requester_id == me:
            return FriendRequestActionResponse(message="Friend request sent", status="pending")
        # We declined THEIR old request, and now we are the ones asking: reopen it with us as requester
        _check_limits(db, me)
        row.requester_id = me
        row.status = STATUS_PENDING
        row.updated_at = now_utc()
        db.commit()
        return FriendRequestActionResponse(message="Friend request sent", status="pending")

    _check_limits(db, me)
    db.add(Friendship(user_low=low, user_high=high, requester_id=me, status=STATUS_PENDING))
    try:
        db.commit()
    except IntegrityError:
        # Both sides sent at the same moment and the other request won: treat as already sent
        db.rollback()
        return FriendRequestActionResponse(message="Friend request already sent", status="pending")
    return FriendRequestActionResponse(message="Friend request sent", status="pending")


def _check_limits(db: Session, me: str) -> None:
    pending_out = (
        db.query(Friendship)
        .filter(Friendship.status == STATUS_PENDING, Friendship.requester_id == me)
        .count()
    )
    if pending_out >= MAX_PENDING_OUTGOING_REQUESTS:
        raise api_error(429, "too_many_requests", "You have too many pending friend requests")
    if len(accepted_rows(db, me)) >= MAX_FRIENDS:
        raise api_error(409, "friend_limit_reached", f"You can have up to {MAX_FRIENDS} friends")


def _accept(db: Session, row: Friendship, me: str, requester_person) -> FriendRequestActionResponse:
    if len(accepted_rows(db, me)) >= MAX_FRIENDS:
        raise api_error(409, "friend_limit_reached", f"You can have up to {MAX_FRIENDS} friends")
    row.status = STATUS_ACCEPTED
    row.updated_at = now_utc()
    db.commit()
    return FriendRequestActionResponse(
        message="You are now friends", status="accepted", friend=to_friend(requester_person)
    )


def _incoming_pending(db: Session, request_id: str, me: str) -> Friendship:
    """The pending request `request_id` that was sent TO me, or a 404."""
    row = (
        db.query(Friendship)
        .filter(
            Friendship.id == request_id,
            Friendship.status == STATUS_PENDING,
            Friendship.requester_id != me,
            or_(Friendship.user_low == me, Friendship.user_high == me),
        )
        .first()
    )
    if row is None:
        raise api_error(404, "request_not_found", "Friend request not found")
    return row


@router.post("/requests/{request_id}/accept", response_model=FriendRequestActionResponse)
def accept_friend_request(
    request_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_own_username(db, current_user)
    row = _incoming_pending(db, request_id, current_user.id)
    people = load_people(db, [row.requester_id])
    if row.requester_id not in people:
        raise api_error(404, "request_not_found", "Friend request not found")
    return _accept(db, row, current_user.id, people[row.requester_id])


@router.post("/requests/{request_id}/decline", response_model=FriendRequestActionResponse)
def decline_friend_request(
    request_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Declines quietly. The sender is not notified and can't tell it was declined."""
    row = _incoming_pending(db, request_id, current_user.id)
    row.status = STATUS_DECLINED
    row.updated_at = now_utc()
    db.commit()
    return FriendRequestActionResponse(message="Friend request declined", status="none")


@router.delete("/requests/{request_id}", response_model=FriendRequestActionResponse)
def cancel_friend_request(
    request_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancels a request YOU sent that hasn't been answered yet."""
    me = current_user.id
    row = (
        db.query(Friendship)
        .filter(
            Friendship.id == request_id,
            Friendship.status == STATUS_PENDING,
            Friendship.requester_id == me,
        )
        .first()
    )
    if row is None:
        raise api_error(404, "request_not_found", "Friend request not found")
    db.delete(row)
    db.commit()
    return FriendRequestActionResponse(message="Friend request cancelled", status="none")


@router.get("/activity", response_model=FriendActivityListResponse)
def friends_activity(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Friends' activity; poll every 30-60s. `status` is listening|paused|recent|idle|online;
    `online` (separate bool) is the green circle: any heartbeat in the last 5 min."""
    me = current_user.id
    rows = accepted_rows(db, me)
    friend_ids = [other_user_id(r, me) for r in rows]
    people = load_people(db, friend_ids)

    playing: Dict[str, NowPlaying] = {}
    if people:
        playing = {
            np.user_id: np
            for np in db.query(NowPlaying).filter(NowPlaying.user_id.in_(list(people.keys()))).all()
        }

    seen: Dict[str, UserPresence] = {}
    if people:
        seen = {
            p.user_id: p
            for p in db.query(UserPresence).filter(UserPresence.user_id.in_(list(people.keys()))).all()
        }

    now = now_utc()
    items: List[FriendActivity] = []
    for fid, (profile, user) in people.items():
        np = playing.get(fid)

        # Online = the app was active recently: a heartbeat OR a now-playing update counts.
        stamps = [as_utc(p.last_seen_at) for p in [seen.get(fid)] if p is not None]
        if np is not None:
            stamps.append(as_utc(np.updated_at))
        online = bool(stamps) and (now - max(stamps)).total_seconds() <= LIVE_WINDOW_SECONDS

        base = {"username": profile.username, "name": user.name, "online": online}

        if not profile.share_listening:
            # Sharing is off: never reveal the song or exact times, only whether they are around right now.
            items.append(FriendActivity(status=STATUS_ONLINE if online else STATUS_IDLE, **base))
            continue

        if np is None:
            items.append(FriendActivity(status=STATUS_IDLE, **base))
            continue

        updated = as_utc(np.updated_at)
        age = max(0, int((now - updated).total_seconds()))

        if age > RECENT_WINDOW_SECONDS:
            items.append(FriendActivity(status=STATUS_IDLE, **base))
            continue

        if age <= LIVE_WINDOW_SECONDS:
            status = STATUS_LISTENING if np.is_playing else STATUS_PAUSED
        else:
            status = STATUS_RECENT

        items.append(
            FriendActivity(
                status=status,
                song=SongSnapshot(
                    song_id=np.song_id,
                    title=np.title,
                    artist=np.artist,
                    album=np.album,
                    image_url=np.image_url,
                    perma_url=np.perma_url,
                ),
                updated_at=updated,
                seconds_ago=age,
                **base,
            )
        )

    order = {STATUS_LISTENING: 0, STATUS_ONLINE: 1, STATUS_PAUSED: 2, STATUS_RECENT: 3, STATUS_IDLE: 4}
    items.sort(
        key=lambda a: (
            order[a.status],
            0 if a.online else 1,
            a.seconds_ago if a.seconds_ago is not None else 0,
            a.username,
        )
    )
    return FriendActivityListResponse(items=items, server_time=now)


@router.delete("/{username}", response_model=FriendRequestActionResponse)
def remove_friend(
    username: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Unfriends by username. Safe to call twice."""
    me = current_user.id
    target_profile = (
        db.query(UserProfile).filter(UserProfile.username == normalize_username(username)).first()
    )
    if target_profile is not None:
        low, high = sorted_pair(me, target_profile.user_id)
        row = (
            db.query(Friendship)
            .filter(
                Friendship.user_low == low,
                Friendship.user_high == high,
                Friendship.status == STATUS_ACCEPTED,
            )
            .first()
        )
        if row is not None:
            db.delete(row)
            db.commit()
            return FriendRequestActionResponse(message="Friend removed", status="none")
    return FriendRequestActionResponse(message="You are not friends with that user", status="none")
