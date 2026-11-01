"""Native <select> popups follow the theme on every page: the select carries the theme's
color-scheme and every option has explicit token colours, so a dark theme never opens a
white popup with light text (seen in Edge/Chrome on Windows)."""
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
CSS = (APP / "static" / "ui" / "exam-room.css").read_text(encoding="utf-8")


def test_select_color_scheme_follows_every_theme_state():
    assert "select { color-scheme: light; }" in CSS
    assert ':root[data-theme="dark"] select { color-scheme: dark; }' in CSS
    assert '@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) select { color-scheme: dark; } }' in CSS


def test_options_take_their_colours_from_the_theme_tokens():
    assert "select option, select optgroup { background-color: var(--paper); color: var(--ink); }" in CSS
    # No later rule gives options a transparent background or another colour.
    later = CSS[CSS.index("select option, select optgroup"):]
    assert not re.search(r"option[^{]*\{[^}]*background(-color)?:\s*(transparent|none)", later)


def test_every_page_uses_the_shared_stylesheet_for_its_selects():
    for page in (APP / "templates").glob("*.html"):
        html = page.read_text(encoding="utf-8")
        if "<select" in html:
            assert '/ui-static/exam-room.css' in html, page.name
            assert "<option style=" not in html and "<select style=" not in html, page.name


def _lum(hex_colour):
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def test_option_text_meets_aa_in_every_theme_block():
    """--ink on --paper (and --muted for disabled options) in each token block: the default
    look's light and dark, and the Trading floor's light and dark."""
    blocks = [m for m in re.findall(r"\{([^{}]*--paper:[^{}]*)\}", CSS) if "--ink:" in m]
    assert len(blocks) >= 6  # default: light, dark (system), dark (toggle); floor: the same three
    for block in blocks:
        tokens = dict(re.findall(r"--(paper|ink|muted):\s*(#[0-9a-fA-F]{6})", block))
        for fg in ("ink", "muted"):
            a, b = _lum(tokens[fg]), _lum(tokens["paper"])
            ratio = (max(a, b) + 0.05) / (min(a, b) + 0.05)
            assert ratio >= 4.5, (fg, tokens, round(ratio, 2))
