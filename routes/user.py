import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.user import User, UserLogin, UserSignUp

router = APIRouter(prefix="/user", tags=["User"])


@router.post("/signup")
def signup(user_data: UserSignUp, db: Session = Depends(get_db)):

    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="User with this email already exists")

    hashed_password = bcrypt.hashpw(user_data.password.encode("utf-8"), bcrypt.gensalt())

    new_user = User(
        name=user_data.name,
        email=user_data.email,
        password=hashed_password,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "Signup successful",
        "user": {
            "id": new_user.id,
            "name": new_user.name,
            "email": new_user.email,
        },
    }


@router.post("/signin")
def signin(credentials: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    is_valid = bcrypt.checkpw(credentials.password.encode("utf-8"), bytes(user.password))
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return {
        "message": "Login successful",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
        },
    }
