"""Minimal HTTP application scaffold."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.database import initialize_database
from app.voice_routes import router as voice_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Unbluffable", lifespan=lifespan)
app.include_router(voice_router)
app.mount("/voice-static", StaticFiles(directory=Path(__file__).parent / "static"), name="voice-static")
app.mount("/ui-static", StaticFiles(directory=Path(__file__).parent / "static" / "ui"), name="ui-static")

TEMPLATES = Path(__file__).parent / "templates"


@app.get("/", response_class=HTMLResponse)
def health_page() -> str:
    """Return a small human-readable health page."""
    return "<!doctype html><html><head><title>Unbluffable</title></head><body><h1>Unbluffable</h1><p>Service is running.</p><a href='/practice'>Start voice practice</a></body></html>"


@app.get("/practice")
def voice_practice():
    return FileResponse(Path(__file__).parent / "static" / "practice.html")


@app.get("/health")
def health() -> dict[str, str]:
    """Return machine-readable service health."""
    return {"status": "ok"}


# UI preview screens (Exam Room design, fake data; not wired to the engine yet).
@app.get("/ui")
def ui_landing():
    return FileResponse(TEMPLATES / "landing.html")


@app.get("/ui/interview")
def ui_interview():
    return FileResponse(TEMPLATES / "interview.html")


@app.get("/ui/end")
def ui_end():
    return FileResponse(TEMPLATES / "end.html")
