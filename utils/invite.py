import os
import secrets
from datetime import timedelta

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from models.signup_attempt import SignupAttempt
from utils.time_utils import now_utc

# Secret code a new user must enter to create an account. Change it by setting the
# SIGNUP_INVITE_CODE environment variable (e.g. in Vercel); this default is used when it is unset.
DEFAULT_SIGNUP_INVITE_CODE = "427842"

# Lock an IP out after this many wrong codes within the window.
MAX_WRONG_CODES = 10
LOCKOUT_WINDOW = timedelta(minutes=15)
# Old attempt rows are deleted after this long.
ATTEMPT_RETENTION = timedelta(days=1)


def expected_invite_code() -> str:
    return (os.getenv("SIGNUP_INVITE_CODE") or DEFAULT_SIGNUP_INVITE_CODE).strip()


def client_ip(request: Request) -> str:
    """Vercel puts the real client address first in X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def verify_invite_code(db: Session, request: Request, supplied: str) -> None:
    """Passes if `supplied` is the right invite code; 403 if wrong, 429 after too many guesses
    from this IP. Constant-time compare; `detail` stays a plain string for the Flutter screen."""
    ip = client_ip(request)
    now = now_utc()

    recent_wrong = (
        db.query(SignupAttempt)
        .filter(SignupAttempt.ip == ip, SignupAttempt.created_at >= now - LOCKOUT_WINDOW)
        .count()
    )
    if recent_wrong >= MAX_WRONG_CODES:
        raise HTTPException(
            status_code=429,
            detail="Too many incorrect invite codes. Please try again later.",
        )

    if secrets.compare_digest((supplied or "").strip().encode(), expected_invite_code().encode()):
        return

    db.add(SignupAttempt(ip=ip, created_at=now))
    db.query(SignupAttempt).filter(SignupAttempt.created_at < now - ATTEMPT_RETENTION).delete(
        synchronize_session=False
    )
    db.commit()
    raise HTTPException(status_code=403, detail="Invalid invite code")
