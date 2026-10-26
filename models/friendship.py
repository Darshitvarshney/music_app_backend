import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, TEXT, UniqueConstraint, func
from database import Base

STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_DECLINED = "declined"


# One row per pair of users; (user_low, user_high) is the sorted pair, so the DB blocks
# duplicate or crossed requests. `requester_id` records who asked.
class Friendship(Base):
    __tablename__ = "friendships"

    id = Column(TEXT, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_low = Column(TEXT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    user_high = Column(TEXT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    requester_id = Column(TEXT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(TEXT, nullable=False, default=STATUS_PENDING)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_low", "user_high", name="uq_friendship_pair"),
        CheckConstraint("user_low < user_high", name="ck_friendship_pair_sorted"),
    )


# Pydantic Schemas
class FriendRequestInput(BaseModel):
    username: str = Field(..., max_length=64, description="Username of the person to add")


class FriendResponse(BaseModel):
    username: str
    name: str
    since: Optional[datetime] = None


class FriendListResponse(BaseModel):
    total: int
    items: List[FriendResponse]


class FriendRequestItem(BaseModel):
    id: str
    username: str
    name: str
    created_at: Optional[datetime] = None


class FriendRequestListResponse(BaseModel):
    incoming: List[FriendRequestItem]
    outgoing: List[FriendRequestItem]


class FriendRequestActionResponse(BaseModel):
    message: str
    # "pending" (request is waiting), "accepted" (now friends), "none" (nothing outstanding)
    status: str
    friend: Optional[FriendResponse] = None
