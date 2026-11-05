import os
import threading
from dotenv import load_dotenv
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

Base = declarative_base()

if DATABASE_URL:
    # Ensure postgresql:// schema is used (convert postgres:// if provided by cloud providers like Supabase/Neon/Heroku)
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    try:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    except Exception as e:
        print(f"Engine creation failed: {e}")
        engine = None
        SessionLocal = None
else:
    engine = None
    SessionLocal = None



_tables_ready = False
_tables_lock = threading.Lock()


def _migrate_room_columns():
    """Adds playback sync columns to rooms table if they do not exist."""
    if engine is None:
        return
    try:
        with engine.begin() as conn:
            dialect_name = engine.dialect.name
            columns = [
                ("is_playing", "BOOLEAN NOT NULL DEFAULT TRUE" if dialect_name == "postgresql" else "INTEGER NOT NULL DEFAULT 1"),
                ("playback_position_ms", "INTEGER NOT NULL DEFAULT 0"),
                ("playback_updated_at", "TIMESTAMPTZ" if dialect_name == "postgresql" else "DATETIME"),
                ("playback_seq", "INTEGER NOT NULL DEFAULT 0"),
                ("volume", "DOUBLE PRECISION NOT NULL DEFAULT 1.0" if dialect_name == "postgresql" else "FLOAT NOT NULL DEFAULT 1.0"),
                ("playback_changed_by", "TEXT REFERENCES users(id) ON DELETE SET NULL" if dialect_name == "postgresql" else "TEXT"),
            ]
            for col_name, col_def in columns:
                try:
                    if dialect_name == "postgresql":
                        conn.exec_driver_sql(f"ALTER TABLE rooms ADD COLUMN IF NOT EXISTS {col_name} {col_def};")
                    else:
                        conn.exec_driver_sql(f"ALTER TABLE rooms ADD COLUMN {col_name} {col_def};")
                except Exception:
                    pass
    except Exception as e:
        print(f"Room table column migration notice: {e}")


def ensure_tables():
    """Creates missing tables once per process. Called from `get_db` because the lifespan
    hook isn't guaranteed on Vercel; adds missing columns to existing tables."""
    global _tables_ready
    if _tables_ready or engine is None:
        return
    with _tables_lock:
        if _tables_ready:
            return
        try:
            Base.metadata.create_all(bind=engine)
            _migrate_room_columns()
            _tables_ready = True
        except Exception as e:
            # Leave the flag unset so the next request retries
            print(f"Database table initialization warning: {e}")


def get_db():
    if SessionLocal is None:
        raise HTTPException(
            status_code=500,
            detail="DATABASE_URL environment variable is not configured.",
        )
    ensure_tables()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

