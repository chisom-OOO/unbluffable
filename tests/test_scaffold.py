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


def test_pages_are_not_cached_and_assets_carry_the_version(monkeypatch) -> None:
    import re
    from app import pages
    client = TestClient(app)
    for path in ("/ui", "/ui/interview", "/ui/end", "/ui/profile", "/ui/welcome"):
        response = client.get(path)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-cache"
        assets = re.findall(r'(?:src|href)="(/ui-static/[^"]+)"', response.text)
        assert assets and all(a.endswith(f"?v={pages.VERSION}") for a in assets), assets
    assert client.get(f"/ui-static/ui.js?v={pages.VERSION}").status_code == 200
    # On Render, the deploy's commit is the version.
    monkeypatch.setenv("RENDER_GIT_COMMIT", "0123456789abcdef0123")
    assert pages._version() == "0123456789ab"
    assert 'src="/ui-static/ui.js?v=0123456789ab"' in pages.render("landing.html", "0123456789ab")


def test_landing_recording_is_off_until_one_is_committed(tmp_path, monkeypatch) -> None:
    import json
    import app.main as main
    client = TestClient(app)
    monkeypatch.setattr(main, "RECORDING", tmp_path / "recorded-interview.json")
    assert client.get("/api/landing-recording").json() == {"available": False}
    (tmp_path / "recorded-interview.json").write_text("{not json", encoding="utf-8")
    assert client.get("/api/landing-recording").json() == {"available": False}
    rec = {"version": 1, "kind": "unbluffable-recorded-interview", "label": "supports",
           "events": [{"t": 0, "type": "question", "text": "Q?"}, {"t": 10, "type": "answer_complete", "transcript": "A."}]}
    (tmp_path / "recorded-interview.json").write_text(json.dumps(rec), encoding="utf-8")
    assert client.get("/api/landing-recording").json() == rec
