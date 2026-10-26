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


def ensure_tables():
    """Creates missing tables once per process. Called from `get_db` because the lifespan
    hook isn't guaranteed on Vercel; never alters existing tables."""
    global _tables_ready
    if _tables_ready or engine is None:
        return
    with _tables_lock:
        if _tables_ready:
            return
        try:
            Base.metadata.create_all(bind=engine)
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

