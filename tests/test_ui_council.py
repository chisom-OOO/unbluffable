"""UI council fixes, pinned: room readability, the inline verdict, one turn indicator,
idle copy, the camera's place, setup's Start row, the landing's order and chips, and
the selector's focus ring."""
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
CSS = (APP / "static" / "ui" / "exam-room.css").read_text(encoding="utf-8")
JS = (APP / "static" / "ui" / "interview.js").read_text(encoding="utf-8")
ROOM = (APP / "templates" / "interview.html").read_text(encoding="utf-8")
LANDING = (APP / "templates" / "landing.html").read_text(encoding="utf-8")


def _lum(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(a, b):
    a, b = _lum(a), _lum(b)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def test_room_text_sizes():
    assert ".room .says { font-size: 18px; line-height: 1.5; }" in CSS
    assert ".room .speaker { font-size: 14px; }" in CSS
    assert ".market-quotes th, .market-book dt { font-size: 14px; }" in CSS


def test_room_grey_is_stronger_than_the_page_grey_in_every_theme():
    # (room muted, page paper) per theme: default light/dark, floor light/dark.
    for muted, paper in (("#4a443b", "#fbf9f4"), ("#bdb7ad", "#1a1a19"), ("#46494e", "#fefdfb"), ("#bcc1c7", "#212428")):
        assert f"--muted: {muted};" in CSS
        assert _ratio(muted, paper) >= 7, (muted, paper)


def test_verdict_row_is_inline_and_never_shows_the_exact_answer():
    assert 'verdictRow(stated || event.extraction?.committed_answer_text, event.observation)' in JS
    assert '"matches the exact answer"' in JS and '"not the exact answer"' in JS
    assert "checked in code" in JS
    assert ".verdict-row.wrong, .verdict-row.wrong b { color: var(--amber); }" in CSS


def test_challenged_number_is_underlined_in_amber():
    assert re.search(r"\.room mark, \.room mark\.challenged \{ background: linear-gradient\(var\(--amber\), var\(--amber\)\)", CSS)


def test_one_turn_indicator():
    for label in ('"Interviewer speaking"', '"Your turn — speak when ready"', '"Checking your working"'):
        assert label in JS
    assert "Your answer ends when you pause, or press Done." in ROOM
    assert 'phase = "starting";' in JS  # Start is not "checking": that comes only after an answer
    assert ".voicebar .orb { width: 32px; height: 32px; }" in CSS
    assert ".voicetext strong { font-size: 17px; }" in CSS


def test_idle_copy_and_hidden_counts():
    assert "Press Start and the interviewer will read the first question." in ROOM
    assert "reads the first question when you start" not in ROOM + JS
    assert '<p class="fine" id="help-count" aria-live="polite" hidden></p>' in ROOM
    assert '$("help-count").hidden = !(c.challenges || c.nudges || c.hints);' in JS
    assert ">Candidate<" not in ROOM


def test_camera_sits_at_the_top_of_the_rail():
    rail = ROOM[ROOM.index('<aside class="rail"'):]
    assert rail.index('id="selfview"') < rail.index("<section")
    assert ".rail .selfview { width: 160px;" in CSS


def test_setup_start_row_and_checks():
    assert ".btn.not-ready { opacity: .4; }" in CSS
    assert "dashed" not in CSS[CSS.index(".btn.not-ready"):CSS.index(".btn.not-ready") + 200]
    assert re.search(r'<div class="start-row">\s*<button class="btn not-ready"[^>]*id="start"[^>]*>[^<]*</button>\s*<p class="gate-note"', ROOM)
    assert 'input[type="checkbox"] { accent-color: var(--active, var(--ink));' in CSS
    assert "skeleton" not in ROOM
    assert 'id="all-passed" hidden' in ROOM and "All checks passed" in ROOM
    assert 'micStatus === "ok" && camera === "ok" && connection === "ok"' in JS
    assert '<input type="radio" name="level" value="Easy" checked>' in ROOM
    assert '<option value="quant" selected>Quant</option>' in LANDING


def test_landing_start_is_under_the_headline_and_proof_is_three_chips():
    assert LANDING.index("</h1>") < LANDING.index('class="go"') < LANDING.index('class="scene')
    chips = re.findall(r'<li><a href="/ui/forge">([^<]+)</a></li>', LANDING)
    assert chips == ["Muse Voice Transcribe", "Muse Spark Open · open weights", "Exact maths in code"]
    assert "text-decoration: none" in CSS[CSS.index(".proof a {"):CSS.index(".proof a {") + 300]


def test_selector_focus_ring():
    assert ".select-wrap select:focus-visible { outline: 2px solid var(--brand, var(--ink)); outline-offset: 3px;" in CSS
