import uuid
from datetime import datetime
from typing import List, Optional, Union
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, ForeignKey, Integer, TEXT, UniqueConstraint, func
from database import Base

MAX_PLAYLIST_NAME_LENGTH = 80
MAX_PLAYLIST_DESCRIPTION_LENGTH = 300


# Database Model (PostgreSQL table: playlists)
class Playlist(Base):
    __tablename__ = "playlists"

    id = Column(TEXT, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(TEXT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Name as typed (shown in the UI) and a normalized key so "Gym" and " gym " collide
    name = Column(TEXT, nullable=False)
    name_key = Column(TEXT, nullable=False)
    description = Column(TEXT, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "name_key", name="uq_user_playlist_name"),
    )


# Database Model (PostgreSQL table: playlist_songs). Same metadata snapshot as favorite_songs.
class PlaylistSong(Base):
    __tablename__ = "playlist_songs"

    id = Column(TEXT, primary_key=True, default=lambda: str(uuid.uuid4()))
    playlist_id = Column(TEXT, ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False, index=True)

    song_id = Column(TEXT, nullable=False, index=True)
    perma_url = Column(TEXT, nullable=False)

    title = Column(TEXT, nullable=False)
    artist = Column(TEXT, nullable=True)
    album = Column(TEXT, nullable=True)
    image_url = Column(TEXT, nullable=True)
    duration = Column(TEXT, nullable=True)
    language = Column(TEXT, nullable=True)
    year = Column(TEXT, nullable=True)

    # 1-based play order inside the playlist (append = max + 1)
    position = Column(Integer, nullable=False, default=0)
    added_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("playlist_id", "song_id", name="uq_playlist_song"),
    )


# Pydantic Schemas
class PlaylistCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=MAX_PLAYLIST_NAME_LENGTH)
    description: Optional[str] = Field(None, max_length=MAX_PLAYLIST_DESCRIPTION_LENGTH)


class PlaylistUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=MAX_PLAYLIST_NAME_LENGTH)
    description: Optional[str] = Field(None, max_length=MAX_PLAYLIST_DESCRIPTION_LENGTH)


class PlaylistSongCreate(BaseModel):
    song_id: str = Field(..., description="Unique song ID from JioSaavn")
    perma_url: str
    title: str
    artist: Optional[str] = None
    album: Optional[str] = None
    image_url: Optional[str] = None
    duration: Optional[Union[str, int]] = None
    language: Optional[str] = None
    year: Optional[str] = None


class PlaylistSongResponse(BaseModel):
    id: str
    song_id: str
    perma_url: str
    title: str
    artist: Optional[str] = None
    album: Optional[str] = None
    image_url: Optional[str] = None
    duration: Optional[str] = None
    language: Optional[str] = None
    year: Optional[str] = None
    position: int = 0
    added_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PlaylistSummary(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    song_count: int = 0
    # Up to 4 artwork URLs for a collage cover
    cover_images: List[str] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PlaylistDetail(PlaylistSummary):
    songs: List[PlaylistSongResponse] = []


class PlaylistListResponse(BaseModel):
    items: List[PlaylistSummary]


class PlaylistActionResponse(BaseModel):
    message: str
    playlist: Optional[PlaylistSummary] = None


class PlaylistSongActionResponse(BaseModel):
    message: str
    added: bool = False
    playlist: Optional[PlaylistSummary] = None


class PlaylistMembershipResponse(BaseModel):
    song_id: str
    playlist_ids: List[str]
