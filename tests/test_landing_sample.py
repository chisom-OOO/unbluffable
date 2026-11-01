"""The landing samples, one per track, each from a real forge family: the question is the
family's own, the candidate commits to one of its verified wrong-method values, the challenge
never gives the answer, and the recovery reaches the stored answer. Every number in every
line is checked against the family."""
from fractions import Fraction
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "app"
SAMPLES_JS = UI / "static" / "ui" / "landing-samples.js"
NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def samples() -> dict:
    text = SAMPLES_JS.read_text(encoding="utf-8")
    body = re.search(r"window\.UB_SAMPLES = (\{.*\});", text, re.S)[1]
    body = re.sub(r"^\s*//[^\n]*", "", body, flags=re.M)
    body = re.sub(r"^(\s*)(\w+):", r'\1"\2":', body, flags=re.M)          # unquoted keys at line start
    body = re.sub(r'([{,]\s*)(\w+):(?=\s)', r'\1"\2":', body)               # unquoted keys inside { ... }
    body = re.sub(r",(\s*[}\]])", r"\1", body)                              # trailing commas
    return json.loads(body)


def family(fid: str) -> dict:
    return json.loads((ROOT / "content" / "forge" / f"{fid}.json").read_text(encoding="utf-8"))


def numbers(text: str) -> list[Fraction]:
    return [Fraction(n.replace(",", "")) for n in NUMBER.findall(text)]


def test_one_sample_per_track_from_the_right_pack():
    data = samples()
    assert list(data) == ["quant", "ib", "consulting", "software"]
    for track, s in data.items():
        assert family(s["family"])["pack"] == track, track
    assert (ROOT / "content" / "coding" / f"{data['software']['family']}.json").exists()  # a coding family


def test_every_number_matches_the_family():
    for track, s in samples().items():
        fam = family(s["family"])
        first = fam["instances"][0]
        assert s["question"] == first["text"], track
        assert s["spoken"] == first["spoken_text"], track
        answer = Fraction(first["answer"])
        wrong = {Fraction(w["value"]): w["misconceptions"] for w in first["wrong"]}
        opening, challenge, recovery = s["lines"]
        assert [(line["who"], line.get("kind")) for line in s["lines"]] == [("candidate", None), ("interviewer", "challenge"), ("candidate", None)]
        # The committed number is a verified wrong-method value, for the named mistake.
        committed = Fraction(opening["value"])
        assert committed in wrong and s["mistake"] in wrong[committed], track
        assert committed != answer
        assert committed in numbers(opening["text"]) and opening["challenge"] in opening["text"], track
        assert Fraction(opening["value"]) in numbers(opening["challenge"]), track
        # The challenge quotes their own number and never gives the answer.
        assert committed in numbers(challenge["text"]), track
        assert answer not in numbers(challenge["text"]), track
        assert "?" in challenge["text"]
        # The recovery reaches the stored answer.
        assert Fraction(recovery["value"]) == answer and answer in numbers(recovery["text"]), track
        # Any other number is from the question itself (or the wrong value being corrected).
        allowed = set(numbers(first["text"])) | {answer, committed}
        for line in s["lines"]:
            assert set(numbers(line["text"])) <= allowed, (track, line["text"], set(numbers(line["text"])) - allowed)


def test_lines_are_full_sentences_short_enough_to_say():
    for track, s in samples().items():
        for line in s["lines"]:
            text = line["text"]
            assert not text.startswith(("…", "...")), (track, text)
            assert text[0].isupper() and text.endswith((".", "?")), (track, text)
            assert len(text) <= 100, (track, text)


def test_landing_follows_the_track_and_reads_the_question_first():
    js = (UI / "static" / "ui" / "landing.js").read_text(encoding="utf-8")
    assert "const SAMPLES = window.UB_SAMPLES;" in js
    assert "swapSample();" in js and "if (!reducedMotion()) { void scene.offsetWidth; scene.classList.add(\"swap\"); }" in js
    assert 'speakOne(real ? $("landing-puzzle").textContent : sample.spoken, "interviewer"' in js
    assert "const candidate = pickVoice(interviewer);" in js
    html = (UI / "templates" / "landing.html").read_text(encoding="utf-8")
    assert '/ui-static/landing-samples.js' in html and "fake-data.js" not in html


def test_landing_keeps_the_sample_label_and_offers_sound():
    html = (UI / "templates" / "landing.html").read_text(encoding="utf-8")
    assert ">Sample<" in html and "Play with sound" in html and 'id="mute"' in html
    js = (UI / "static" / "ui" / "landing.js").read_text(encoding="utf-8")
    assert "Your browser has no speech voice" in js
    for page in (html, js, SAMPLES_JS.read_text(encoding="utf-8")):
        assert "fraud" not in page.lower()
