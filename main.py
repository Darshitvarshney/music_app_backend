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

except Exception:
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse

    err_trace = traceback.format_exc()
    app = FastAPI()

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
    async def fallback(path: str = ""):
        return PlainTextResponse(f"Startup Exception Traceback:\n\n{err_trace}", status_code=500)


