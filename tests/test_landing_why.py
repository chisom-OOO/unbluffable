"""The landing page carries no "Why these numbers?" example any more (it lives in the
interview room and the report), and no screenshot."""
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
LANDING = APP / "templates" / "landing.html"


def test_landing_has_no_why_these_numbers_section():
    page = LANDING.read_text(encoding="utf-8")
    assert "Why these numbers?" not in page and "why-example" not in page
    css = (APP / "static" / "ui" / "exam-room.css").read_text(encoding="utf-8")
    assert ".why-example" not in css and ".why-receipt" not in css
    # Still in the room and the report.
    assert "Why these numbers?" in (APP / "templates" / "interview.html").read_text(encoding="utf-8")


def test_landing_has_no_screenshot():
    page = LANDING.read_text(encoding="utf-8")
    assert "<img" not in page and ".webp" not in page


def test_landing_is_hero_left_sample_right_from_1280px():
    page = LANDING.read_text(encoding="utf-8")
    hero, scene = page.index('<div class="hero">'), page.index('<div class="scene sample replay"')
    assert hero < page.index("</h1>") < page.index('class="go"') < page.index('class="proof"') < scene
    css = (APP / "static" / "ui" / "exam-room.css").read_text(encoding="utf-8")
    block = css[css.index("@media (min-width: 1280px) {\n  .landing-stage"):]
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)" in block[:300]
    # Nothing about the radar on the landing page.
    assert "radar" not in page
