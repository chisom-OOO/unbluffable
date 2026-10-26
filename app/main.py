"""Minimal HTTP application scaffold."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.database import initialize_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Unbluffable", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
def health_page() -> str:
    """Return a small human-readable health page."""
    return "<!doctype html><html><head><title>Unbluffable</title></head><body><h1>Unbluffable</h1><p>Service is running.</p></body></html>"


@app.get("/health")
def health() -> dict[str, str]:
    """Return machine-readable service health."""
    return {"status": "ok"}
