"""Small UI fixes the product owner asked for, pinned so they do not regress."""
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
TEMPLATES = APP / "templates"
UI = APP / "static" / "ui"


def read(path):
    return path.read_text(encoding="utf-8")


def test_trading_floor_is_the_default_look_and_default_switches_back():
    for page in TEMPLATES.glob("*.html"):
        html = read(page)
        assert '<html lang="en" data-look="floor">' in html, page.name
        # ?look=default is remembered and removes the look before the first paint; ?look=floor returns.
        assert 'if(q==="default")localStorage.setItem("ub-look",q)' in html, page.name
        assert 'if(localStorage.getItem("ub-look")==="default")d.removeAttribute("data-look")' in html, page.name


def test_report_has_no_estimate_panel():
    assert "Your estimate" not in read(TEMPLATES / "end.html")
    assert 'id="progress-body"' not in read(TEMPLATES / "end.html")
    assert "progress-body" not in read(UI / "end.js")


def test_typed_status_says_it_is_your_turn():
    assert '"Your turn — type your answer"' in read(UI / "interview.js")


def test_drill_names_the_mistake():
    assert "Mistake: ${escapeHtml(d.misconception)}" in read(UI / "end.js")
    assert "Mistake: ${escapeHtml(e.drill.misconception)}" in read(UI / "end.js")
    assert "`Mistake: ${drillMistake}`" in read(UI / "interview.js")


def test_models_panel_is_open_and_names_the_open_weights_host():
    assert '<details class="models" open>' in read(TEMPLATES / "interview.html")
    assert "open weights · Baseten" in read(UI / "interview.js")


def test_why_these_numbers_opens_once_shown():
    assert '$("why").open = !!event.why;' in read(UI / "interview.js")


def test_forge_page_says_which_code_is_stored():
    html = read(TEMPLATES / "forge.html")
    assert "For written questions the code is not stored, only these verification figures" in html
    assert "for coding questions the solver code is kept and shown in each question's receipt" in html


def test_transcript_question_lines_point_up():
    assert '"(question above)"' in read(UI / "interview.js")
