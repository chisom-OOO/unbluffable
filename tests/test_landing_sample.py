"""The landing sample: a dice question whose exact answer the candidate recovers to."""
from fractions import Fraction
from itertools import product
import json
from pathlib import Path
import re

UI = Path(__file__).resolve().parents[1] / "app"


def sample():
    text = (UI / "static" / "ui" / "fake-data.js").read_text(encoding="utf-8")
    body = re.search(r"window\.UB_FAKE = (\{.*\});", text, re.S)[1]
    body = re.sub(r"//[^\n]*", "", body)
    body = re.sub(r"(\w+):", r'"\1":', body)            # unquoted keys
    body = re.sub(r",(\s*[}\]])", r"\1", body)          # trailing commas
    return json.loads(body)


def test_sample_is_the_dice_question_with_its_exact_answer():
    data = sample()
    assert data["puzzle"]["text"] == ("I roll two fair dice numbered one to nine and tell you the total is sixteen. "
                                      "What's the chance the first die is above seven?")
    pairs = [(a, b) for a, b in product(range(1, 10), repeat=2) if a + b == 16]
    assert pairs == [(7, 9), (8, 8), (9, 7)]
    assert Fraction(sum(a > 7 for a, _ in pairs), len(pairs)) == Fraction(2, 3)
    who = [(line["who"], line.get("kind")) for line in data["replay"]["lines"]]
    assert who == [("candidate", None), ("interviewer", "challenge"), ("candidate", None)]
    opening, challenge, recovery = (line["text"] for line in data["replay"]["lines"])
    assert opening.endswith("so about a half, one half.")
    assert challenge == "You said a half. Which pairs actually give sixteen, and how many have the first die above seven?"
    assert recovery == "Seven-nine, eight-eight, nine-seven. Two of three, so two thirds."
    # The words the challenge quotes are the candidate's own.
    assert data["replay"]["lines"][0]["challenge"] in opening


def test_landing_keeps_the_sample_label_and_offers_sound():
    html = (UI / "templates" / "landing.html").read_text(encoding="utf-8")
    assert ">Sample<" in html and "Play with sound" in html and 'id="mute"' in html
    js = (UI / "static" / "ui" / "landing.js").read_text(encoding="utf-8")
    assert "Your browser has no speech voice" in js
    for page in (html, js, (UI / "static" / "ui" / "fake-data.js").read_text(encoding="utf-8")):
        assert "fraud" not in page.lower()
