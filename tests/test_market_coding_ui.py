"""Market making and the coding round in the room: the market scorecard (no empty table
before the first quote), and the coding console's readable, not-colour-only results."""
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
CSS = (APP / "static" / "ui" / "exam-room.css").read_text(encoding="utf-8")
JS = (APP / "static" / "ui" / "interview.js").read_text(encoding="utf-8")
ROOM = (APP / "templates" / "interview.html").read_text(encoding="utf-8")


def test_market_shows_one_line_before_the_first_quote():
    panel = ROOM[ROOM.index('id="market-panel"'):ROOM.index("</section>", ROOM.index('id="market-panel"'))]
    assert "Say your bid and offer, e.g. ‘9 at 12’." in panel
    assert '<div class="market-card" id="market-card" hidden>' in panel
    for empty in ("No quote yet", "None yet", "Nothing revealed yet", "<table"):
        assert empty not in panel and empty not in JS[JS.index("function marketState"):JS.index("// ---------- Turns")]
    assert '$("market-hint").hidden = quoted;' in JS and '$("market-card").hidden = !quoted;' in JS


def test_market_scorecard_is_large_mono_and_at_least_14px():
    assert ".market-num { font: 500 28px/1.15 var(--mono);" in CSS
    assert ".market-label { font-size: 14px;" in CSS
    assert ".market-book dt { font-size: 14px;" in CSS
    # The trade and the reveal: one line each, hidden until there is one.
    assert 'id="market-trade-line" hidden' in ROOM and 'id="market-reveal-line" hidden' in ROOM


def test_trade_wording_follows_the_side():
    # side +1: the candidate bought, so the interviewer sold to them.
    assert "t.side > 0 ? `sold to you at ${t.price}` : `bought from you at ${t.price}`" in JS


def test_code_results_are_14px_with_an_icon_and_a_word():
    assert '.code-case.ok .code-mark::before { content: "✓"; }' in CSS
    assert '.code-case.bad .code-mark::before { content: "✗"; }' in CSS
    rule = CSS[CSS.index(".code-results, .code-results h3, .code-case code"):]
    assert rule[:rule.index("}")].endswith("{ font-size: 14px; ")
    assert '"Passed" : "Failed"' in (APP / "static" / "ui" / "coding-ui.js").read_text(encoding="utf-8")
