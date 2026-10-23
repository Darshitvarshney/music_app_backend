from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from models.favorite import (
    BatchStatusRequest,
    BatchStatusResponse,
    FavoriteActionResponse,
    FavoriteCreate,
    FavoriteListResponse,
    FavoriteResponse,
    FavoriteSong,
    FavoriteStatusResponse,
)
from models.user import User
from utils.auth import get_current_user

router = APIRouter(prefix="/favorites", tags=["Favorites"])


@router.post("", response_model=FavoriteActionResponse, status_code=status.HTTP_201_CREATED)
def add_favorite(
    payload: FavoriteCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Adds a song to the authenticated user's liked songs.
    Stores the JioSaavn perma_url alongside basic metadata snapshot for fast client-side rendering.
    """
    # Check if song is already favorited by this user
    existing = (
        db.query(FavoriteSong)
        .filter(FavoriteSong.user_id == current_user.id, FavoriteSong.song_id == payload.song_id)
        .first()
    )

    if existing:
        return FavoriteActionResponse(
            message="Song is already in your favorites",
            is_liked=True,
            favorite=existing,
        )

    # Convert duration to string if provided
    duration_str = str(payload.duration) if payload.duration is not None else None

    new_favorite = FavoriteSong(
        user_id=current_user.id,
        song_id=payload.song_id,
        perma_url=payload.perma_url,
        title=payload.title,
        artist=payload.artist,
        album=payload.album,
        image_url=payload.image_url,
        duration=duration_str,
        language=payload.language,
        year=payload.year,
    )

    db.add(new_favorite)
    db.commit()
    db.refresh(new_favorite)

    return FavoriteActionResponse(
        message="Song added to favorites",
        is_liked=True,
        favorite=new_favorite,
    )


@router.delete("/{song_id}", response_model=FavoriteActionResponse)
def remove_favorite(
    song_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Removes a song from the authenticated user's favorites by song_id.
    """
    favorite = (
        db.query(FavoriteSong)
        .filter(FavoriteSong.user_id == current_user.id, FavoriteSong.song_id == song_id)
        .first()
    )

    if not favorite:
        return FavoriteActionResponse(
            message="Song is not in your favorites",
            is_liked=False,
            favorite=None,
        )

    db.delete(favorite)
    db.commit()

    return FavoriteActionResponse(
        message="Song removed from favorites",
        is_liked=False,
        favorite=None,
    )


@router.get("", response_model=FavoriteListResponse)
def list_favorites(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieves the authenticated user's liked songs list sorted by most recently liked.
    """
    base_query = db.query(FavoriteSong).filter(FavoriteSong.user_id == current_user.id)
    total = base_query.count()

    items = (
        base_query.order_by(FavoriteSong.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return FavoriteListResponse(
        total=total,
        page=page,
        limit=limit,
        items=items,
    )


@router.get("/{song_id}/status", response_model=FavoriteStatusResponse)
def check_favorite_status(
    song_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Checks if a specific song is currently liked by the authenticated user.
    """
    is_liked = (
        db.query(FavoriteSong.id)
        .filter(FavoriteSong.user_id == current_user.id, FavoriteSong.song_id == song_id)
        .first()
        is not None
    )

    return FavoriteStatusResponse(
        song_id=song_id,
        is_liked=is_liked,
    )


@router.post("/status-batch", response_model=BatchStatusResponse)
def check_favorite_status_batch(
    payload: BatchStatusRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Batch-checks a list of song IDs to see which ones are liked by the current user.
    Very efficient for search results or album tracklists.
    """
    if not payload.song_ids:
        return BatchStatusResponse(liked_song_ids=[])

    liked_records = (
        db.query(FavoriteSong.song_id)
        .filter(
            FavoriteSong.user_id == current_user.id,
            FavoriteSong.song_id.in_(payload.song_ids),
        )
        .all()
    )

    liked_ids = [record[0] for record in liked_records]
    return BatchStatusResponse(liked_song_ids=liked_ids)
