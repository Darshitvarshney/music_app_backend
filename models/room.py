import uuid
from datetime import datetime
from typing import List, Optional, Union
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, ForeignKey, Integer, TEXT, UniqueConstraint, func
from database import Base

MAX_ROOM_MEMBERS = 3  # joined members + pending invites together

MEMBER_INVITED = "invited"
MEMBER_JOINED = "joined"


# The shared song lives on the row; `song_seq` bumps on every change so clients just
# compare numbers.
class Room(Base):
    __tablename__ = "rooms"

    id = Column(TEXT, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_by = Column(TEXT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    song_seq = Column(Integer, nullable=False, default=0)
    song_id = Column(TEXT, nullable=True)
    perma_url = Column(TEXT, nullable=True)
    title = Column(TEXT, nullable=True)
    artist = Column(TEXT, nullable=True)
    album = Column(TEXT, nullable=True)
    image_url = Column(TEXT, nullable=True)
    duration = Column(TEXT, nullable=True)
    language = Column(TEXT, nullable=True)
    year = Column(TEXT, nullable=True)
    song_changed_by = Column(TEXT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    song_changed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# Database Model (PostgreSQL table: room_members)
class RoomMember(Base):
    __tablename__ = "room_members"

    id = Column(TEXT, primary_key=True, default=lambda: str(uuid.uuid4()))
    room_id = Column(TEXT, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(TEXT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    invited_by = Column(TEXT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    status = Column(TEXT, nullable=False, default=MEMBER_INVITED)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    joined_at = Column(DateTime(timezone=True), nullable=True)
    # Updated on each poll; shows who is connected
    last_seen_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("room_id", "user_id", name="uq_room_member"),
    )


# Pydantic Schemas
class RoomCreate(BaseModel):
    usernames: List[str] = Field(default_factory=list, max_length=MAX_ROOM_MEMBERS - 1,
                                 description="Friends to invite straight away (optional)")


class RoomInvite(BaseModel):
    username: str = Field(..., max_length=64, description="Username of the friend to invite")


class RoomSongInput(BaseModel):
    song_id: str
    perma_url: Optional[str] = None
    title: str
    artist: Optional[str] = None
    album: Optional[str] = None
    image_url: Optional[str] = None
    duration: Optional[Union[str, int]] = None
    language: Optional[str] = None
    year: Optional[str] = None
    # True when the previous song ended on its own
    auto: bool = False
    # song_seq the sender saw; drops duplicate auto-advances
    expected_seq: Optional[int] = None


class RoomSong(BaseModel):
    song_id: str
    perma_url: Optional[str] = None
    title: str
    artist: Optional[str] = None
    album: Optional[str] = None
    image_url: Optional[str] = None
    duration: Optional[str] = None
    language: Optional[str] = None
    year: Optional[str] = None


class RoomMemberInfo(BaseModel):
    username: str
    name: str
    status: str  # joined | invited
    online: bool = False
    is_me: bool = False


class RoomState(BaseModel):
    id: str
    capacity: int = MAX_ROOM_MEMBERS
    song_seq: int = 0
    song: Optional[RoomSong] = None
    song_changed_by: Optional[str] = None  # username
    song_changed_at: Optional[datetime] = None
    members: List[RoomMemberInfo] = []


class RoomInviteItem(BaseModel):
    room_id: str
    invited_by_username: Optional[str] = None
    invited_by_name: Optional[str] = None
    member_count: int = 0
    created_at: Optional[datetime] = None


class CurrentRoomResponse(BaseModel):
    room: Optional[RoomState] = None
    invites: List[RoomInviteItem] = []


class RoomActionResponse(BaseModel):
    message: str
    room: Optional[RoomState] = None


class RoomSongResponse(BaseModel):
    # False if nothing changed (same song, or another phone advanced first)
    applied: bool
    message: str
    room: RoomState
