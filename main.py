from contextlib import asynccontextmanager
from fastapi import FastAPI
from database import engine, SessionLocal, Base
from models.user import User  # Registers table schema with Base
from routes.user import router as user_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Automatically create tables in PostgreSQL if database engine is configured
    if engine:
        try:
            Base.metadata.create_all(bind=engine)
        except Exception as e:
            print(f"Database table initialization warning: {e}")
    yield


app = FastAPI(lifespan=lifespan)

app.include_router(user_router)


@app.get("/")
async def root():
    return {"message": "Hello World"}

