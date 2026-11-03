"""Minimal HTTP application scaffold."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.database import initialize_database
from app.pages import page
from app.model_diagnostics import log_startup_models
from app.voice_routes import router as voice_router
from app.firebase_config import router as firebase_router
from app.interest import router as interest_router
from app.interview_routes import router as interview_router, warm
from app.byoq import router as byoq_router
from app.security import SecurityHeaders


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    await log_startup_models()
    # The question bank and the topics response are ready before the first request.
    await asyncio.to_thread(warm)
    yield


app = FastAPI(title="Unbluffable", lifespan=lifespan)
app.add_middleware(SecurityHeaders)  # decision log 42
app.include_router(voice_router)
app.include_router(interview_router)
app.include_router(byoq_router)
app.include_router(interest_router)
app.include_router(firebase_router)
app.mount("/voice-static", StaticFiles(directory=Path(__file__).parent / "static"), name="voice-static")
app.mount("/ui-static", StaticFiles(directory=Path(__file__).parent / "static" / "ui"), name="ui-static")

# The site opens on the landing page; /health stays for Render.
@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/ui", status_code=307)


@app.get("/privacy", include_in_schema=False)
def privacy_short():
    return RedirectResponse("/ui/privacy", status_code=307)


@app.get("/practice", include_in_schema=False)
def old_practice():
    return RedirectResponse("/ui", status_code=307)


RECORDING = Path(__file__).resolve().parents[1] / "content" / "landing" / "recorded-interview.json"


@app.get("/api/landing-recording", include_in_schema=False)
def landing_recording():
    """The landing page's "A real recorded interview": an exported, text-only timeline once one
    is committed; until then {"available": false} and the scripted sample plays."""
    import json
    try:
        data = json.loads(RECORDING.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"available": False}
    if data.get("version") != 1 or data.get("kind") != "unbluffable-recorded-interview" or not isinstance(data.get("events"), list):
        return {"available": False}
    return data


@app.get("/health")
def health() -> dict[str, str]:
    """Return machine-readable service health."""
    return {"status": "ok"}


# The Exam Room screens (no-cache HTML, versioned script and stylesheet URLs: app.pages).
@app.get("/ui")
def ui_landing():
    return page("landing.html")


@app.get("/ui/interview")
def ui_interview():
    return page("interview.html")


@app.get("/ui/end")
def ui_end():
    return page("end.html")


@app.get("/ui/profile")
def ui_profile():
    return page("profile.html")


@app.get("/ui/forge")
def ui_forge():
    return page("forge.html")


@app.get("/ui/byoq")
def ui_byoq():
    return page("byoq.html")


@app.get("/ui/welcome")
def ui_welcome():
    return page("welcome.html")


@app.get("/ui/privacy")
def ui_privacy():
    return page("privacy.html")
