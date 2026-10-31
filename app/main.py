"""Minimal HTTP application scaffold."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.database import initialize_database
from app.model_diagnostics import log_startup_models
from app.voice_routes import router as voice_router
from app.interest import router as interest_router
from app.interview_routes import router as interview_router, warm


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    await log_startup_models()
    # The question bank and the topics response are ready before the first request.
    await asyncio.to_thread(warm)
    yield


app = FastAPI(title="Unbluffable", lifespan=lifespan)
app.include_router(voice_router)
app.include_router(interview_router)
app.include_router(interest_router)
app.mount("/voice-static", StaticFiles(directory=Path(__file__).parent / "static"), name="voice-static")
app.mount("/ui-static", StaticFiles(directory=Path(__file__).parent / "static" / "ui"), name="ui-static")

TEMPLATES = Path(__file__).parent / "templates"


# The site opens on the landing page; /health stays for Render.
@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/ui", status_code=307)


@app.get("/practice", include_in_schema=False)
def old_practice():
    return RedirectResponse("/ui", status_code=307)


@app.get("/health")
def health() -> dict[str, str]:
    """Return machine-readable service health."""
    return {"status": "ok"}


# The Exam Room screens.
@app.get("/ui")
def ui_landing():
    return FileResponse(TEMPLATES / "landing.html")


@app.get("/ui/interview")
def ui_interview():
    return FileResponse(TEMPLATES / "interview.html")


@app.get("/ui/end")
def ui_end():
    return FileResponse(TEMPLATES / "end.html")


@app.get("/ui/profile")
def ui_profile():
    return FileResponse(TEMPLATES / "profile.html")


@app.get("/ui/welcome")
def ui_welcome():
    return FileResponse(TEMPLATES / "welcome.html")
