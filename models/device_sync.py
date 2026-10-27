from datetime import datetime
from typing import Optional, Union
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, TEXT
from database import Base

# 24h, just a sanity cap on what a client may report
MAX_POSITION_MS = 24 * 60 * 60 * 1000


# Database Model (PostgreSQL table: device_sync) - one row per user, overwritten in place.
# `position_ms` was true at `position_at`, so a playing song is extrapolated on read.
class DeviceSync(Base):
    __tablename__ = "device_sync"

    user_id = Column(TEXT, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    seq = Column(Integer, nullable=False, default=0)

    song_id = Column(TEXT, nullable=True)
    perma_url = Column(TEXT, nullable=True)
    title = Column(TEXT, nullable=True)
    artist = Column(TEXT, nullable=True)
    album = Column(TEXT, nullable=True)
    image_url = Column(TEXT, nullable=True)
    duration = Column(TEXT, nullable=True)
    language = Column(TEXT, nullable=True)
    year = Column(TEXT, nullable=True)

    is_playing = Column(Boolean, nullable=False, default=False)
    position_ms = Column(Integer, nullable=False, default=0)
    position_at = Column(DateTime(timezone=True), nullable=True)

    updated_by = Column(TEXT, nullable=True)  # device id
    updated_at = Column(DateTime(timezone=True), nullable=True)


# Pydantic Schemas
class DeviceSyncInput(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    song_id: str = Field(..., min_length=1, max_length=100)
    perma_url: Optional[str] = Field(None, max_length=1000)
    title: str = Field(..., min_length=1, max_length=300)
    artist: Optional[str] = Field(None, max_length=300)
    album: Optional[str] = Field(None, max_length=300)
    image_url: Optional[str] = Field(None, max_length=1000)
    duration: Optional[Union[str, int]] = None
    language: Optional[str] = Field(None, max_length=100)
    year: Optional[str] = Field(None, max_length=20)
    is_playing: bool
    position_ms: int = Field(0, ge=0, le=MAX_POSITION_MS)
    # True when the previous song ended on its own
    auto: bool = False
    # seq the sender saw; drops duplicate auto-advances from several devices
    expected_seq: Optional[int] = None


class DeviceSyncSong(BaseModel):
    song_id: str
    perma_url: Optional[str] = None
    title: str
    artist: Optional[str] = None
    album: Optional[str] = None
    image_url: Optional[str] = None
    duration: Optional[str] = None
    language: Optional[str] = None
    year: Optional[str] = None


class DeviceSyncState(BaseModel):
    seq: int = 0
    song: Optional[DeviceSyncSong] = None
    is_playing: bool = False
    # Already moved forward to `server_time` when the song is playing
    position_ms: int = 0
    server_time: datetime
    updated_by_device_id: Optional[str] = None
    updated_at: Optional[datetime] = None


class DeviceSyncPutResponse(BaseModel):
    # False when nothing changed (same state, or another device advanced first)
    applied: bool
    state: DeviceSyncState
