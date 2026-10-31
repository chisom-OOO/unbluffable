"""Evidence items (decision log 15): choosing the 40 question pairs and checking each
transcript against its category with exact maths. No model calls, no network.

Categories and labels:
  correct        both answers commit to the exact value                      understands
  memorised      right on the original; the twin repeats the original's
                 answer or is otherwise wrong                                does_not_understand
  misconception  both answers commit to the item's named wrong value        does_not_understand
  slip           right on the original; the twin commits a number that is
                 not its answer, not a named wrong value and not the
                 original's answer (an arithmetic slip, spec/05 hard set)   understands (SLIP_LABEL)

The committed number is the last number stated in the transcript (words such as
"two thirds" are read as numbers); it must match its target within the instance's
tolerance, exactly as the engine's checker accepts answers.
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter, OrderedDict
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.bank import NamedValue, parse_instance, parse_template, same_mistake, twin_choice  # noqa: E402
from engine.checker import _iter_values, accepts  # noqa: E402

FORGE = ROOT / "content" / "forge"
DRAFT = ROOT / "eval" / "items_draft.json"
COUNTS = OrderedDict([("memorised", 10), ("misconception", 10), ("slip", 5), ("correct", 15)])
SLIP_LABEL = "understands"  # right reasoning with an arithmetic slip; confirm before the freeze
LABELS = {"correct": "understands", "memorised": "does_not_understand",
          "misconception": "does_not_understand", "slip": SLIP_LABEL}
SOURCES = ("builder", "tester", "model-written")
SEED = 15  # decision log 15


def value_text(x: Fraction) -> str:
    x = Fraction(x)
    return str(x.numerator) if x.denominator == 1 else f"{x.numerator}/{x.denominator} (≈ {float(x):.4g})"


# --- Choosing items --------------------------------------------------------------------

def quant_families(directory: Path = FORGE) -> list[tuple[dict, object]]:
    """(raw JSON, parsed template) for every Quant family with verified misconceptions."""
    out = []
    for path in sorted(directory.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("pack", "quant") != "quant" or not raw.get("verification", {}).get("misconceptions_verified"):
            continue
        out.append((raw, parse_template(raw, path.name)))
    return out


def _named(inst) -> list[NamedValue]:
    return [nv for nv in inst.wrong if nv.value != inst.answer]


def _original_index(template, rng) -> int | None:
    pool = [i for i, inst in enumerate(template.instances) if inst.interview_friendly and _named(inst)]
    return rng.choice(pool) if pool else None


def _spread(families, rng) -> list:
    """Families in round-robin order across topics, so 40 picks cover as many topics as possible."""
    by_topic: dict[str, list] = {}
    for fam in families:
        by_topic.setdefault(fam[1].topic, []).append(fam)
    for group in by_topic.values():
        rng.shuffle(group)
    order, topics = [], sorted(by_topic)
    while any(by_topic[t] for t in topics):
        for t in topics:
            if by_topic[t]:
                order.append(by_topic[t].pop())
    return order


def make_items(directory: Path = FORGE, seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    plan = [c for c, n in COUNTS.items() for _ in range(n)]
    rng.shuffle(plan)
    items = []
    for raw, template in _spread(quant_families(directory), rng):
        if len(items) == len(plan):
            break
        category = plan[len(items)]
        original = _original_index(template, rng)
        if original is None:
            continue
        first = template.instances[original]
        suspect = None
        if category == "misconception":
            # A named mistake whose value differs from the answer on both the original and the twin.
            for nv in sorted(_named(first), key=lambda nv: nv.misconception):
                twin, _ = twin_choice(template, original, random.Random(rng.random()), nv.misconception)
                second = template.instances[twin]
                if any(same_mistake(w.misconception, nv.misconception) and w.value != second.answer for w in second.wrong):
                    suspect = nv.misconception
                    break
            if suspect is None:
                continue
        else:
            twin, _ = twin_choice(template, original, random.Random(rng.random()))
            second = template.instances[twin]
        if category in ("memorised", "slip") and second.answer == first.answer:
            continue  # repeating the original's answer must be detectable
        items.append({
            "id": f"e{len(items) + 1:02d}", "label": LABELS[category], "category": category, "source": "",
            "template_id": template.template_id, "topic": template.topic, "difficulty": template.difficulty,
            "misconception": suspect,
            "instance_index": {"original": original, "twin": twin},  # in content/forge, for provenance
            "original": {"question": raw["instances"][original], "transcript": ""},
            "twin": {"question": raw["instances"][twin], "transcript": ""},
        })
    if len(items) < len(plan):
        raise ValueError(f"only {len(items)} items could be made; {len(plan)} are needed")
    return items


def write(path: Path, items: list[dict]) -> None:
    """Atomic save, so an interrupted fill never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"version": 1, "items": items}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def read(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("items"), list):
        raise ValueError("not an item file (version 1 with an items list)")
    return data["items"]


# --- Checking transcripts --------------------------------------------------------------

def _instance(item: dict, part: str):
    return parse_instance(item[part]["question"], f"{item['id']}.{part}.question")


def committed(transcript: str):
    """The last number stated, or None."""
    found = [stated for _, stated in _iter_values(transcript)]
    return found[-1] if found else None


def target(item: dict, part: str) -> str:
    """What the transcript must commit to, in words, for the person filling it in."""
    inst, first = _instance(item, part), _instance(item, "original")
    c = item["category"]
    if c == "correct" or part == "original" and c in ("memorised", "slip"):
        return f"the exact answer {value_text(inst.answer)}, with sound reasoning"
    if c == "misconception":
        nv = next(w for w in inst.wrong if same_mistake(w.misconception, item["misconception"]))
        return f"the wrong value {value_text(nv.value)} ({item['misconception']}), reasoning that follows that mistake"
    if c == "memorised":
        return (f"the original's answer {value_text(first.answer)} again, or another wrong number "
                f"(not {value_text(inst.answer)})")
    return (f"a slip: a number that is not {value_text(inst.answer)}, not a named wrong value and not "
            f"{value_text(first.answer)}, with the right method")


def check(item: dict, part: str, transcript: str) -> tuple[bool, str]:
    """Whether the transcript's committed number fits the item's category for this part."""
    if not transcript.strip():
        return False, "empty transcript"
    said = committed(transcript)
    if said is None:
        return False, "no number found; state the committed number (digits or words)"
    inst, first = _instance(item, part), _instance(item, "original")
    right = accepts(said, inst.answer, inst.tolerance)
    c = item["category"]
    if c == "correct" or part == "original" and c in ("memorised", "slip"):
        return (True, "commits to the exact answer") if right else (False, f"commits to {said.value}, not the exact answer {value_text(inst.answer)}")
    if c == "misconception":
        nv = next((w for w in inst.wrong if same_mistake(w.misconception, item["misconception"])), None)
        if nv is not None and accepts(said, nv.value, inst.tolerance) and not right:
            return True, f"commits to the named wrong value ({item['misconception']})"
        return False, f"must commit to {value_text(nv.value) if nv else '?'} ({item['misconception']})"
    if right:
        return False, f"the twin's answer {value_text(inst.answer)} is right; this category needs it wrong"
    if c == "memorised":
        return True, "repeats the original's answer" if accepts(said, first.answer, inst.tolerance) else "fails the twin"
    named = [w for w in inst.wrong if accepts(said, w.value, inst.tolerance)]
    if named:
        return False, f"that is a named wrong value ({named[0].misconception}), not a slip"
    if accepts(said, first.answer, inst.tolerance):
        return False, "that repeats the original's answer, not a slip"
    return True, "a wrong number that is not a named error: a slip"


def problems(items: list[dict]) -> list[str]:
    """Everything that stops a freeze: counts, labels, sources and every transcript's check."""
    out = []
    counts = Counter(i.get("category") for i in items)
    if dict(counts) != dict(COUNTS):
        out.append(f"categories {dict(counts)} must be {dict(COUNTS)}")
    for item in items:
        if item.get("label") != LABELS.get(item.get("category")):
            out.append(f"{item['id']}: label {item.get('label')} does not match category {item.get('category')}")
        if item.get("source") not in SOURCES:
            out.append(f"{item['id']}: source must be one of {SOURCES}")
        for part in ("original", "twin"):
            ok, why = check(item, part, item[part]["transcript"])
            if not ok:
                out.append(f"{item['id']}.{part}: {why}")
    return out
