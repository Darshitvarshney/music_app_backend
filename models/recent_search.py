import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, ForeignKey, TEXT, UniqueConstraint, func
from database import Base

MAX_QUERY_LENGTH = 200


# Database Model (PostgreSQL table: recent_searches)
class RecentSearch(Base):
    __tablename__ = "recent_searches"

    id = Column(TEXT, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(TEXT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Query as the user typed it (shown in the UI) and a normalized key for de-duplication
    query = Column(TEXT, nullable=False)
    query_key = Column(TEXT, nullable=False)

    # Bumped every time the same query is searched again; drives ordering
    searched_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "query_key", name="uq_user_recent_search"),
    )


# Pydantic Schemas
class RecentSearchCreate(BaseModel):
    query: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH, description="Search text the user submitted")


class RecentSearchResponse(BaseModel):
    id: str
    query: str
    searched_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RecentSearchListResponse(BaseModel):
    items: List[RecentSearchResponse]


class RecentSearchActionResponse(BaseModel):
    message: str
    item: Optional[RecentSearchResponse] = None
