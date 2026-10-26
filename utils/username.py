import re
from typing import Optional

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 20

# Lowercase letters, digits and underscores; must start with a letter.
_USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,19}$")

# Words that would collide with routes or look official.
RESERVED_USERNAMES = frozenset(
    {
        "admin", "administrator", "root", "support", "help", "official", "system",
        "moderator", "mod", "staff", "team", "null", "undefined", "none", "me", "you",
        "requests", "request", "activity", "friends", "friend", "profile", "settings",
        "api", "music", "musicapp", "spotify", "jiosaavn", "anonymous",
    }
)


def normalize_username(raw: str) -> str:
    """Usernames are case-insensitive; the canonical form is trimmed lowercase."""
    return (raw or "").strip().lower()


def username_problem(normalized: str) -> Optional[str]:
    """Returns a human-readable reason the username is invalid, or None if it is fine."""
    if len(normalized) < USERNAME_MIN_LENGTH or len(normalized) > USERNAME_MAX_LENGTH:
        return f"Username must be {USERNAME_MIN_LENGTH}-{USERNAME_MAX_LENGTH} characters long"
    if not normalized[0].isalpha() or not normalized[0].isascii():
        return "Username must start with a letter"
    if not _USERNAME_PATTERN.match(normalized):
        return "Username can only contain letters, numbers and underscores"
    if normalized in RESERVED_USERNAMES:
        return "That username is reserved"
    return None


def slugify_for_username(name: str) -> str:
    """Best-effort username base from a display name or email prefix."""
    slug = re.sub(r"[^a-z0-9_]+", "_", (name or "").strip().lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    if not slug or not slug[0].isalpha():
        slug = "user_" + slug if slug else "user"
    return slug[: USERNAME_MAX_LENGTH - 5].rstrip("_") or "user"
