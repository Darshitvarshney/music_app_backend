import secrets
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models.profile import (
    ProfileResponse,
    SettingsInput,
    UserProfile,
    UsernameAvailabilityResponse,
    UsernameInput,
)
from models.user import User
from utils.api_error import api_error
from utils.auth import get_current_user
from utils.time_utils import as_utc, now_utc
from utils.username import normalize_username, slugify_for_username, username_problem

router = APIRouter(prefix="/profile", tags=["Profile"])

# After CHANGING a username (not the first claim) the user must wait this long to change it again.
USERNAME_CHANGE_COOLDOWN = timedelta(days=30)


def get_profile(db: Session, user_id: str) -> Optional[UserProfile]:
    return db.query(UserProfile).filter(UserProfile.user_id == user_id).first()


def get_or_create_profile(db: Session, user_id: str) -> UserProfile:
    profile = get_profile(db, user_id)
    if profile is None:
        profile = UserProfile(user_id=user_id, share_listening=True)
        db.add(profile)
        try:
            db.flush()
        except IntegrityError:
            # Another request created it first
            db.rollback()
            profile = get_profile(db, user_id)
            if profile is None:
                raise
    return profile


def change_available_at(profile: Optional[UserProfile]):
    """When the user may next change their username, or None if they can do so now."""
    if profile is None or profile.username is None or profile.username_changed_at is None:
        return None
    available_at = as_utc(profile.username_changed_at) + USERNAME_CHANGE_COOLDOWN
    return available_at if available_at > now_utc() else None


def username_taken(db: Session, normalized: str, exclude_user_id: Optional[str] = None) -> bool:
    query = db.query(UserProfile.user_id).filter(UserProfile.username == normalized)
    if exclude_user_id:
        query = query.filter(UserProfile.user_id != exclude_user_id)
    return query.first() is not None


def suggest_username(db: Session, user: User) -> str:
    base = slugify_for_username(user.name or (user.email or "").split("@")[0])
    candidates = [base] + [f"{base}_{secrets.randbelow(9000) + 1000}" for _ in range(8)]
    for candidate in candidates:
        if username_problem(candidate) is None and not username_taken(db, candidate):
            return candidate
    return f"user_{secrets.token_hex(4)}"


def build_profile_response(db: Session, user: User, profile: Optional[UserProfile]) -> ProfileResponse:
    available_at = change_available_at(profile)
    username = profile.username if profile else None
    return ProfileResponse(
        name=user.name,
        email=user.email,
        username=username,
        can_change_username=available_at is None,
        username_change_available_at=available_at,
        share_listening=profile.share_listening if profile else True,
        suggested_username=suggest_username(db, user) if username is None else None,
    )


@router.get("", response_model=ProfileResponse)
def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The signed-in user's profile. `username` is null until they claim one (see `suggested_username`)."""
    return build_profile_response(db, current_user, get_profile(db, current_user.id))


@router.get("/username-available", response_model=UsernameAvailabilityResponse)
def check_username_available(
    username: str = Query(..., max_length=64),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Live availability check for the username field (requires login to limit enumeration)."""
    normalized = normalize_username(username)
    problem = username_problem(normalized)
    if problem:
        return UsernameAvailabilityResponse(username=normalized, available=False, reason=problem)
    if username_taken(db, normalized, exclude_user_id=current_user.id):
        return UsernameAvailabilityResponse(username=normalized, available=False, reason="That username is already taken")
    return UsernameAvailabilityResponse(username=normalized, available=True)


@router.put("/username", response_model=ProfileResponse)
def set_username(
    payload: UsernameInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Claims the first username (free) or changes it (30-day cooldown, else 429
    `username_cooldown`). Re-submitting the current one is a no-op."""
    normalized = normalize_username(payload.username)
    problem = username_problem(normalized)
    if problem:
        raise api_error(422, "invalid_username", problem)

    profile = get_or_create_profile(db, current_user.id)

    if profile.username == normalized:
        return build_profile_response(db, current_user, profile)

    is_change = profile.username is not None
    if is_change:
        available_at = change_available_at(profile)
        if available_at is not None:
            raise api_error(
                429,
                "username_cooldown",
                "You can change your username once every 30 days",
                can_change_at=available_at.isoformat(),
            )

    if username_taken(db, normalized, exclude_user_id=current_user.id):
        db.rollback()
        raise api_error(409, "username_taken", "That username is already taken")

    profile.username = normalized
    if is_change:
        profile.username_changed_at = now_utc()

    try:
        db.commit()
    except IntegrityError:
        # Lost a race for the same username
        db.rollback()
        raise api_error(409, "username_taken", "That username is already taken")
    db.refresh(profile)

    return build_profile_response(db, current_user, profile)


@router.put("/settings", response_model=ProfileResponse)
def update_settings(
    payload: SettingsInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Privacy: when `share_listening` is false, friends see only that you are online, never the song."""
    profile = get_or_create_profile(db, current_user.id)
    profile.share_listening = payload.share_listening
    db.commit()
    db.refresh(profile)
    return build_profile_response(db, current_user, profile)
