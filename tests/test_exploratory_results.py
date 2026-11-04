"""The README's exploratory lines (decision log 47) match the saved run output in
eval/exploratory/, and the correct-items McNemar p is recomputed with the harness's own stats."""

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "evidence"))

import exploratory  # noqa: E402
import stats  # noqa: E402

RESULTS = json.loads((ROOT / "eval" / "exploratory" / "results.json").read_text(encoding="utf-8"))
ITEMS = json.loads((ROOT / "eval" / "items_draft.json").read_text(encoding="utf-8"))
ITEMS = ITEMS["items"] if isinstance(ITEMS, dict) else ITEMS
CATEGORY = {i["id"]: i["category"] for i in ITEMS}
README = (ROOT / "README.md").read_text(encoding="utf-8")
FLAG = "does_not_understand"


def arm(name):
    return RESULTS["arms"][name]


def correct_items_discordant():
    careful, unb = arm("careful_first_only")["majority"], arm("unbluffable")["majority"]
    ids = [i for i, c in CATEGORY.items() if c == "correct"]
    b = sum(careful[i] == FLAG and unb[i] != FLAG for i in ids)
    c = sum(unb[i] == FLAG and careful[i] != FLAG for i in ids)
    return b, c


def test_the_saved_run_is_complete_on_the_frozen_items():
    assert RESULTS["status"] == "complete" and RESULTS["failures"]["count"] == 0
    assert RESULTS["label"] == exploratory.LABEL
    prov = RESULTS["provenance"]
    assert prov["items_sha256"].startswith("b9aeb7f1") and prov["runs"] == 3 and prov["model"] == "muse-spark-1.3"


def test_the_readme_counts_match_the_saved_run():
    want = {"careful_first_only": {"memorised": 10, "misconception": 10, "slip": 5, "correct": 14},
            "unbluffable": {"memorised": 10, "misconception": 10, "slip": 5, "correct": 1}}
    for name, cats in want.items():
        assert {k: v["flagged"] for k, v in arm(name)["categories"].items()} == cats
    assert arm("unbluffable")["flips"] == []
    flips = arm("careful_first_only")["flips"]
    assert len(flips) == 5 and sorted(CATEGORY[i] for i in flips) == ["correct"] * 4 + ["slip"]
    assert sum(v == FLAG for v in arm("careful_first_only")["majority"].values()) == 39
    flagged_correct = [i for i, v in arm("unbluffable")["majority"].items() if v == FLAG and CATEGORY[i] == "correct"]
    assert flagged_correct == ["e05"]


def test_the_correct_items_mcnemar_p_is_exact_and_in_the_readme():
    b, c = correct_items_discordant()
    assert (b, c) == (13, 0)
    p = stats.mcnemar_exact(b, c)
    assert Fraction(p) == Fraction(1, 4096)
    assert "13 items flagged by the careful arm only, 0 by Unbluffable only, p = 1/4096 ≈ 0.00024" in README


def test_the_readme_section_is_labelled_and_makes_no_general_chatbot_claim():
    head = "### Exploratory, not pre-registered (row 47); 39 of 40 items model-written"
    assert head in README
    section = README[README.index(head):README.index("Run 2 (pre-registered")]
    assert "does not stand for chatbots in general" in section
    for banned in ("can't be fooled", "calibrated", "proves understanding", "beats", "better than chatbots"):
        assert banned not in section.lower()
