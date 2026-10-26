from fastapi.testclient import TestClient

from app.database import append_event, initialize_database
from app.main import app


def test_health_endpoints(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "events.sqlite3"))
    client = TestClient(app)

    with client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Service is running" in page.text

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
