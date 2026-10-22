import os
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



def get_db():
    if SessionLocal is None:
        raise HTTPException(
            status_code=500,
            detail="DATABASE_URL environment variable is not configured.",
        )
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

