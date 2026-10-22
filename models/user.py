import uuid
from pydantic import BaseModel, Field
from sqlalchemy import Column, LargeBinary, TEXT, VARCHAR
from database import Base

# Regex pattern for email validation (e.g. user@domain.com)
EMAIL_REGEX = r"^[\w\.-]+@[\w\.-]+\.\w+$"


# Database Model (PostgreSQL table: users)
class User(Base):
    __tablename__ = "users"

    # Automatically generates a unique UUID string like MongoDB's _id
    id = Column(TEXT, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(VARCHAR(100), nullable=False)
    email = Column(VARCHAR(100), unique=True, index=True, nullable=False)
    password = Column(LargeBinary, nullable=False)


# Pydantic Schemas (Request bodies)
class UserSignUp(BaseModel):
    name: str
    email: str = Field(..., pattern=EMAIL_REGEX, description="Valid email address")
    password: str


class UserLogin(BaseModel):
    email: str = Field(..., pattern=EMAIL_REGEX, description="Valid email address")
    password: str


class UserResponse(BaseModel):
    id: str
    name: str
    email: str

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    message: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshTokenInput(BaseModel):
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

