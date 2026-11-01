"""The landing track picker ("Practise for [Quant] interviews") is never clipped: the select is
as wide as its text plus its own padding plus slack, grows until nothing is clipped, refits on
resize, and doesn't shrink in the sentence. Source checks; the real-browser check is manual."""
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "app" / "static" / "ui"
JS = (UI / "landing.js").read_text(encoding="utf-8")
CSS = (UI / "exam-room.css").read_text(encoding="utf-8")
FIT = JS[JS.index("function fit()"):JS.index("function choose()")]


def test_the_width_counts_the_selects_own_padding_and_border_plus_slack():
    assert "1.25em" not in FIT  # left only ~0.1em for the text once padding-right was taken
    assert "getComputedStyle(pick)" in FIT
    for part in ("paddingLeft", "paddingRight", "borderLeftWidth", "borderRightWidth"):
        assert part in FIT
    assert "SLACK_EM = 0.5" in JS


def test_it_grows_until_the_text_is_not_clipped():
    assert "pick.scrollWidth > pick.clientWidth" in FIT


def test_it_refits_on_resize_debounced_and_after_fonts_load():
    assert 'window.addEventListener("resize", () => { clearTimeout(refit); refit = setTimeout(fit, 120); });' in JS
    assert "document.fonts?.ready.then(fit);" in JS


def test_the_picker_does_not_shrink_in_the_sentence():
    assert ".pick .select-wrap { flex-shrink: 0; }" in CSS
