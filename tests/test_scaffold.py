from fastapi.testclient import TestClient

from app.database import append_event, initialize_database
from app.main import app


def test_health_endpoints(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "events.sqlite3"))
    client = TestClient(app)

    with client:
        # "/" and the old /practice page both open the landing page.
        for path in ("/", "/practice"):
            page = client.get(path, follow_redirects=False)
            assert page.status_code == 307 and page.headers["location"] == "/ui"
        assert "Sounding right" in client.get("/").text

        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_event_log_initializes_and_appends(tmp_path) -> None:
    path = tmp_path / "events.sqlite3"
    initialize_database(path)

    event_id = append_event("session-1", "started", {"source": "test"}, path)

    import sqlite3

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT session_id, event_type, payload_json FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
    assert row == ("session-1", "started", '{"source":"test"}')


def test_nothing_links_the_old_practice_page() -> None:
    from pathlib import Path
    app_dir = Path(__file__).resolve().parents[1] / "app"
    pages = list((app_dir / "templates").glob("*.html")) + list((app_dir / "static" / "ui").glob("*.js"))
    assert pages and not [p.name for p in pages if "practice.html" in p.read_text(encoding="utf-8")]
