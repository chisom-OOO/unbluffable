"""The landing's "Why these numbers?" example is a real twin from the forge bank: the
question, the suspected mistake, the new numbers and the explanation are what the engine
produces for family qx_F002, not invented."""
import html
import random
from pathlib import Path

from app import exam_text as say
from app.provenance import pretty
from engine.bank import Diagnostic, load_bank, twin_choice

LANDING = Path(__file__).resolve().parents[1] / "app" / "templates" / "landing.html"
FAMILY, SUSPECT = "qx_F002", "adds_the_discount_to_the_sale_price"


def test_landing_example_is_the_engines_own_twin():
    page = LANDING.read_text(encoding="utf-8")
    template = load_bank().templates[FAMILY]
    first = template.instances[0]
    wrong = next(nv.value for nv in first.wrong if nv.misconception == SUSPECT)
    # The twin choice is deterministic here: every seed picks the same instance.
    picks = {twin_choice(template, 0, random.Random(seed), SUSPECT)[0] for seed in range(20)}
    assert len(picks) == 1
    index, why = twin_choice(template, 0, random.Random(0), SUSPECT)
    assert why.suspected and why.misconception == SUSPECT
    twin, name = template.instances[index], pretty(SUSPECT)
    gap = lambda a, b: f"|{say.value(a)} − {say.value(b)}| = {say.value(abs(a - b))}"
    expected = [
        first.text, f"<dd>{say.value(first.answer)}</dd>", f"<dd>{name}: {say.value(wrong)}</dd>", f"<dd>{gap(first.answer, wrong)}</dd>",
        twin.text, f"<dd>{say.value(why.correct)}</dd>", f"<dd>{name}: {say.value(why.wrong)}</dd>", f"<dd>{gap(why.correct, why.wrong)}</dd>",
        say.why_numbers(Diagnostic(name, why.correct, why.wrong, True)), f"family {FAMILY}",
    ]
    for text in expected:
        assert html.escape(text, quote=False) in page or text in page, text
    # The new numbers really do separate the two further than the first ones.
    assert abs(why.correct - why.wrong) > abs(first.answer - wrong)


def test_landing_has_no_screenshot():
    page = LANDING.read_text(encoding="utf-8")
    assert "<img" not in page and ".webp" not in page
