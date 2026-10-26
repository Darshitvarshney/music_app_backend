from sqlalchemy import Column, DateTime, Integer, TEXT
from database import Base


# Database Model (PostgreSQL table: signup_attempts)
# One row per WRONG invite code, used to lock out guessing from a single IP address.
class SignupAttempt(Base):
    __tablename__ = "signup_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip = Column(TEXT, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
