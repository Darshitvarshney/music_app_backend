from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, TEXT, VARCHAR, func, true
from database import Base


# Database Model (PostgreSQL table: user_profiles)
# Kept separate from `users` so no ALTER TABLE migration is needed on the live DB.
class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id = Column(TEXT, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)

    # Canonical lowercase username. NULL until the user claims one (multiple NULLs are allowed by UNIQUE).
    username = Column(VARCHAR(20), unique=True, index=True, nullable=True)
    # Set only when an existing username is CHANGED (claiming the first one does not start the cooldown).
    username_changed_at = Column(DateTime(timezone=True), nullable=True)

    # When false, friends see this user as "hidden" instead of what they are playing.
    share_listening = Column(Boolean, nullable=False, default=True, server_default=true())

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# Pydantic Schemas
class UsernameInput(BaseModel):
    username: str = Field(..., max_length=64, description="Desired username (3-20 chars, a-z 0-9 _, starts with a letter)")


class SettingsInput(BaseModel):
    share_listening: bool = Field(..., description="false = friends only see that you are online, not what you play")


class ProfileResponse(BaseModel):
    name: str
    email: str
    username: Optional[str] = None
    can_change_username: bool
    username_change_available_at: Optional[datetime] = None
    share_listening: bool
    suggested_username: Optional[str] = None


class UsernameAvailabilityResponse(BaseModel):
    username: str
    available: bool
    reason: Optional[str] = None
