import uuid
from datetime import datetime
from typing import List, Optional, Union
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, ForeignKey, TEXT, UniqueConstraint, func
from database import Base


# Database Model (PostgreSQL table: favorite_songs)
class FavoriteSong(Base):
    __tablename__ = "favorite_songs"

    id = Column(TEXT, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(TEXT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # JioSaavn Song Identifiers
    song_id = Column(TEXT, nullable=False, index=True)
    perma_url = Column(TEXT, nullable=False)

    # Song metadata snapshot for instant UI rendering
    title = Column(TEXT, nullable=False)
    artist = Column(TEXT, nullable=True)
    album = Column(TEXT, nullable=True)
    image_url = Column(TEXT, nullable=True)
    duration = Column(TEXT, nullable=True)
    language = Column(TEXT, nullable=True)
    year = Column(TEXT, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "song_id", name="uq_user_song_favorite"),
    )


# Pydantic Schemas
class FavoriteCreate(BaseModel):
    song_id: str = Field(..., description="Unique song ID from JioSaavn (e.g. IKc2REl8)")
    perma_url: str = Field(..., description="Permanent URL to fetch fresh song stream")
    title: str = Field(..., description="Song title/name")
    artist: Optional[str] = Field(None, description="Primary artists or singers")
    album: Optional[str] = Field(None, description="Album name")
    image_url: Optional[str] = Field(None, description="Album artwork URL")
    duration: Optional[Union[str, int]] = Field(None, description="Duration in seconds or formatted string")
    language: Optional[str] = Field(None, description="Language of the song")
    year: Optional[str] = Field(None, description="Release year")


class FavoriteResponse(BaseModel):
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
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FavoriteActionResponse(BaseModel):
    message: str
    is_liked: bool
    favorite: Optional[FavoriteResponse] = None


class FavoriteListResponse(BaseModel):
    total: int
    page: int
    limit: int
    items: List[FavoriteResponse]


class FavoriteStatusResponse(BaseModel):
    song_id: str
    is_liked: bool


class BatchStatusRequest(BaseModel):
    song_ids: List[str] = Field(..., description="List of song IDs to check")


class BatchStatusResponse(BaseModel):
    liked_song_ids: List[str]
