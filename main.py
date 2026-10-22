from fastapi import FastAPI
from database import engine, SessionLocal, Base
from models.user import User  # Registers table schema with Base
from routes.user import router as user_router

# Automatically create tables in PostgreSQL if they don't exist
Base.metadata.create_all(bind=engine)

sessionLocal = SessionLocal
db = sessionLocal()

app = FastAPI()

app.include_router(user_router)


@app.get("/")
async def root():
    return {"message": "Hello World"}
