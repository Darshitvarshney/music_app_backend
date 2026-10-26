from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, TEXT
from database import Base

# A "listening"/"paused" state older than this is considered stale and shown as "recent".
LIVE_WINDOW_SECONDS = 5 * 60
# Last-played info older than this is dropped from friends' view entirely.
RECENT_WINDOW_SECONDS = 7 * 24 * 60 * 60

STATUS_LISTENING = "listening"
STATUS_PAUSED = "paused"
STATUS_RECENT = "recent"
STATUS_IDLE = "idle"
# Friend hides what they play but is active right now: friends only see that they are online.
STATUS_ONLINE = "online"


# Database Model (PostgreSQL table: now_playing) - exactly one row per user, overwritten in place
class NowPlaying(Base):
    __tablename__ = "now_playing"

    user_id = Column(TEXT, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    song_id = Column(TEXT, nullable=False)
    title = Column(TEXT, nullable=False)
    artist = Column(TEXT, nullable=True)
    album = Column(TEXT, nullable=True)
    image_url = Column(TEXT, nullable=True)
    perma_url = Column(TEXT, nullable=True)
    is_playing = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime(timezone=True), nullable=False)


# Database Model (PostgreSQL table: user_presence) - when the app was last open/active, one row per user.
# Separate from now_playing so someone browsing without playing music still counts as online.
class UserPresence(Base):
    __tablename__ = "user_presence"

    user_id = Column(TEXT, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)


# Pydantic Schemas
class NowPlayingInput(BaseModel):
    song_id: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=300)
    artist: Optional[str] = Field(None, max_length=300)
    album: Optional[str] = Field(None, max_length=300)
    image_url: Optional[str] = Field(None, max_length=1000)
    perma_url: Optional[str] = Field(None, max_length=1000)
    is_playing: bool = Field(True, description="false = paused")


class SongSnapshot(BaseModel):
    song_id: str
    title: str
    artist: Optional[str] = None
    album: Optional[str] = None
    image_url: Optional[str] = None
    perma_url: Optional[str] = None


class FriendActivity(BaseModel):
    username: str
    name: str
    # listening | online | paused | recent | idle
    status: str
    # Drives the green circle: the friend's app was active within the last 5 minutes
    online: bool = False
    song: Optional[SongSnapshot] = None
    updated_at: Optional[datetime] = None
    seconds_ago: Optional[int] = None


class FriendActivityListResponse(BaseModel):
    items: List[FriendActivity]
    server_time: datetime


class PresenceActionResponse(BaseModel):
    message: str
