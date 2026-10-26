from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models.recent_search import (
    RecentSearch,
    RecentSearchActionResponse,
    RecentSearchCreate,
    RecentSearchListResponse,
)
from models.user import User
from utils.auth import get_current_user

router = APIRouter(prefix="/recent-searches", tags=["Recent Searches"])

# Older entries beyond this many per user are pruned on every save
MAX_RECENT_SEARCHES_PER_USER = 30


def _normalize(query: str) -> str:
    return " ".join(query.split()).lower()


@router.post("", response_model=RecentSearchActionResponse)
def save_recent_search(
    payload: RecentSearchCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Records a search; repeating a query moves it to the top."""
    cleaned = " ".join(payload.query.split())
    key = _normalize(payload.query)
    if not key:
        raise HTTPException(status_code=422, detail="Query must not be blank")

    def find_existing():
        return (
            db.query(RecentSearch)
            .filter(RecentSearch.user_id == current_user.id, RecentSearch.query_key == key)
            .first()
        )

    entry = find_existing()
    if entry:
        entry.query = cleaned
        entry.searched_at = datetime.now(timezone.utc)
    else:
        entry = RecentSearch(
            user_id=current_user.id,
            query=cleaned,
            query_key=key,
            searched_at=datetime.now(timezone.utc),
        )
        db.add(entry)

    try:
        db.commit()
    except IntegrityError:
        # Concurrent insert of the same query: the other request won, just bump it
        db.rollback()
        entry = find_existing()
        if entry is None:
            raise
        entry.query = cleaned
        entry.searched_at = datetime.now(timezone.utc)
        db.commit()
    db.refresh(entry)

    # Keep only the newest MAX_RECENT_SEARCHES_PER_USER entries
    stale_ids = [
        row[0]
        for row in db.query(RecentSearch.id)
        .filter(RecentSearch.user_id == current_user.id)
        .order_by(RecentSearch.searched_at.desc(), RecentSearch.id)
        .offset(MAX_RECENT_SEARCHES_PER_USER)
        .all()
    ]
    if stale_ids:
        db.query(RecentSearch).filter(RecentSearch.id.in_(stale_ids)).delete(synchronize_session=False)
        db.commit()

    return RecentSearchActionResponse(message="Search saved", item=entry)


@router.get("", response_model=RecentSearchListResponse)
def list_recent_searches(
    limit: int = Query(20, ge=1, le=MAX_RECENT_SEARCHES_PER_USER, description="Max items to return"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns the authenticated user's recent searches, newest first."""
    items = (
        db.query(RecentSearch)
        .filter(RecentSearch.user_id == current_user.id)
        .order_by(RecentSearch.searched_at.desc(), RecentSearch.id)
        .limit(limit)
        .all()
    )
    return RecentSearchListResponse(items=items)


@router.delete("", response_model=RecentSearchActionResponse)
def clear_recent_searches(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes the authenticated user's whole search history."""
    db.query(RecentSearch).filter(RecentSearch.user_id == current_user.id).delete(synchronize_session=False)
    db.commit()
    return RecentSearchActionResponse(message="Search history cleared")


@router.delete("/{search_id}", response_model=RecentSearchActionResponse)
def delete_recent_search(
    search_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Removes one entry from the authenticated user's history (idempotent)."""
    deleted = (
        db.query(RecentSearch)
        .filter(RecentSearch.user_id == current_user.id, RecentSearch.id == search_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return RecentSearchActionResponse(
        message="Search removed" if deleted else "Search not found"
    )
