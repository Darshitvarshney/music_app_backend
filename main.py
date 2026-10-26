import os
import sys
import traceback

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

try:
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from database import engine, SessionLocal, Base
    from models.user import User  # Registers table schema with Base
    from models.favorite import FavoriteSong  # Registers favorite_songs schema with Base
    from models.recent_search import RecentSearch  # Registers recent_searches schema with Base
    from models.room import Room, RoomMember  # Registers rooms + room_members schemas with Base
    from models.playlist import Playlist, PlaylistSong  # Registers playlists + playlist_songs schemas with Base
    from models.profile import UserProfile  # Registers user_profiles schema with Base
    from models.signup_attempt import SignupAttempt  # Registers signup_attempts schema with Base
    from models.friendship import Friendship  # Registers friendships schema with Base
    from models.presence import NowPlaying, UserPresence  # Registers now_playing + user_presence schemas with Base
    from routes.user import router as user_router
    from routes.favorite import router as favorite_router
    from routes.recent_search import router as recent_search_router
    from routes.room import router as room_router
    from routes.playlist import router as playlist_router
    from routes.profile import router as profile_router
    from routes.friend import router as friend_router
    from routes.presence import router as presence_router
    from routes.song import router as song_router

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Automatically create tables in PostgreSQL if database engine is configured
        if engine:
            try:
                Base.metadata.create_all(bind=engine)
            except Exception as e:
                print(f"Database table initialization warning: {e}")
        yield

    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    app = FastAPI(lifespan=lifespan)

    # Open CORS, matching the former song_api service (Flask-CORS defaults)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        return JSONResponse(
            status_code=500,
            content={
                "error": str(exc),
                "type": type(exc).__name__,
                "traceback": traceback.format_exc(),
            },
        )

    app.include_router(user_router)
    app.include_router(favorite_router)
    app.include_router(recent_search_router)
    app.include_router(room_router)
    app.include_router(playlist_router)
    app.include_router(profile_router)
    app.include_router(friend_router)
    app.include_router(presence_router)
    app.include_router(song_router)

    @app.get("/")
    async def root():
        return {"message": "Hello World"}

    @app.get("/test-db")
    async def test_db():
        from database import DATABASE_URL, engine
        if not DATABASE_URL:
            return {"status": "error", "message": "DATABASE_URL is not set"}
        sanitized_url = DATABASE_URL
        if "@" in sanitized_url:
            prefix, suffix = sanitized_url.split("@", 1)
            sanitized_url = prefix.split(":")[0] + ":***@" + suffix
        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                res = conn.execute(text("SELECT 1")).scalar()
            # Also ensure tables are created
            Base.metadata.create_all(bind=engine)
            return {"status": "connected", "select_1": res, "db_url": sanitized_url}
        except Exception as e:
            return {
                "status": "connection_failed",
                "error": str(e),
                "type": type(e).__name__,
                "db_url": sanitized_url,
                "traceback": traceback.format_exc(),
            }


except Exception:
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse

    err_trace = traceback.format_exc()
    app = FastAPI()

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
    async def fallback(path: str = ""):
        return PlainTextResponse(f"Startup Exception Traceback:\n\n{err_trace}", status_code=500)


