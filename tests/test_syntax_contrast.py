"""The coding workspace's syntax themes (decision log 27): every token colour is at least
4.5:1 against the editor background, in light, dark (system) and dark (toggle), for the
default look and the Trading floor look."""

import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / "app" / "static" / "ui" / "exam-room.css").read_text(encoding="utf-8")
TOKENS = ("text", "keyword", "def", "variable-2", "string", "number", "comment", "builtin", "property", "meta", "linenum")


def luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def themes() -> list[dict]:
    blocks = re.findall(r"\{([^{}]*--cm-bg:[^{}]*)\}", CSS)  # definitions, not var(--cm-bg) uses
    return [dict(re.findall(r"--cm-([\w-]+):\s*(#[0-9a-fA-F]{6})", block)) for block in blocks]


def test_three_theme_blocks_define_every_token():
    found = themes()
    assert len(found) == 6  # light, dark by system, dark by toggle; default look then floor
    assert found[1] == found[2] and found[4] == found[5]
    assert found[4]["bg"] == "#212428"  # the floor's graphite paper, not One Dark's blue-grey
    for theme in found:
        assert set(TOKENS) <= set(theme)


def test_every_token_is_at_least_4_5_to_1_on_the_editor_background():
    for theme in themes():
        for token in TOKENS:
            ratio = contrast(theme[token], theme["bg"])
            assert ratio >= 4.5, (token, theme[token], theme["bg"], round(ratio, 2))
            assert contrast(theme[token], theme["gutter"]) >= 4.5 if token == "linenum" else True
