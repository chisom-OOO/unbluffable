"""Evidence run 2: build an item file from exported interview timelines (the consented JSON
export the Exam Room makes: "Export this interview (JSON)").

From each session it takes the first new question that has a twin, and that twin; each
question is matched back to its forge instance by its exact text (content/forge), and each
part's transcript is the candidate's first answer to it. The category comes from the command
line per file:

  bluff    label does_not_understand
  genuine  label understands, kept only if both committed answers are right (the committed
           number is the last number stated, checked exactly as the engine's checker does);
           otherwise the session is left out and listed

Writes eval/items_run2_draft.json in the harness's item format; freeze.py checks it unchanged.
No model calls, no network.

  python scripts/evidence/from_sessions.py --bluff a.json b.json --genuine c.json d.json
         [--out eval/items_run2_draft.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import itemcheck  # noqa: E402
from engine import mathtext  # noqa: E402
from engine.bank import parse_instance  # noqa: E402
from engine.checker import accepts  # noqa: E402

OUT = ROOT / "eval" / "items_run2_draft.json"
LABELS = {"bluff": "does_not_understand", "genuine": "understands"}
SOURCE = "tester"  # the candidates' own exported answers


class SessionError(ValueError):
    pass


def instance_index(directory: Path = itemcheck.FORGE) -> dict[str, tuple[dict, int]]:
    """Every forge instance by the question text the Exam Room shows: (template, index)."""
    out = {}
    for path in sorted(directory.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("coding_only"):
            continue
        for i, inst in enumerate(raw.get("instances", [])):
            out.setdefault(" ".join(mathtext.display(inst["text"]).split()), (raw, i))
            out.setdefault(" ".join(inst["text"].split()), (raw, i))
    return out


def pair(timeline: dict) -> tuple[dict, str, dict, str]:
    """(original question event, its first answer, twin question event, its first answer)."""
    if timeline.get("kind") != "unbluffable-recorded-interview" or timeline.get("version") != 1:
        raise SessionError("not an Unbluffable interview export")
    events = timeline.get("events") or []
    questions = [i for i, e in enumerate(events) if e.get("type") == "question"]
    for at, i in enumerate(questions):
        if events[i].get("kind") != "new":
            continue
        nxt = questions[at + 1] if at + 1 < len(questions) else None
        if nxt is None or events[nxt].get("kind") != "twin":
            continue
        first = next((e["transcript"] for e in events[i:nxt] if e.get("type") == "answer_complete"), None)
        end = questions[at + 2] if at + 2 < len(questions) else len(events)
        second = next((e["transcript"] for e in events[nxt:end] if e.get("type") == "answer_complete"), None)
        if first and second:
            return events[i], first, events[nxt], second
    raise SessionError("no answered question with an answered twin")


def right(instance: dict, transcript: str) -> bool:
    said = itemcheck.committed(transcript)
    inst = parse_instance(instance, "instance")
    return said is not None and accepts(said, inst.answer, inst.tolerance)


def item(n: int, category: str, path: Path, timeline: dict, index: dict) -> dict:
    original, first, twin, second = pair(timeline)
    found = []
    for q in (original, twin):
        key = " ".join((q.get("text") or "").split())
        if key not in index:
            raise SessionError(f"question not found in content/forge: {key[:80]}")
        found.append(index[key])
    (template, i), (twin_template, j) = found
    if template["template_id"] != twin_template["template_id"]:
        raise SessionError("the twin is not from the same family")
    inst, twin_inst = template["instances"][i], template["instances"][j]
    if category == "genuine" and not (right(inst, first) and right(twin_inst, second)):
        raise SessionError("genuine, but not both committed answers are right")
    return {"id": f"s{n:02d}", "label": LABELS[category], "category": category, "source": SOURCE,
            "session_file": path.name, "template_id": template["template_id"], "topic": template.get("topic"),
            "difficulty": template.get("difficulty"), "misconception": None, "instance_index": {"original": i, "twin": j},
            "original": {"question": inst, "transcript": first}, "twin": {"question": twin_inst, "transcript": second}}


def build(files: list[tuple[str, Path]], index: dict | None = None) -> tuple[dict, list[str]]:
    index = index if index is not None else instance_index()
    items, skipped = [], []
    for category, path in files:
        try:
            timeline = json.loads(Path(path).read_text(encoding="utf-8"))
            items.append(item(len(items) + 1, category, Path(path), timeline, index))
        except (SessionError, OSError, ValueError, KeyError) as error:
            skipped.append(f"{Path(path).name} ({category}): {error}")
    return {"version": 1, "design": "run2", "items": items}, skipped


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bluff", nargs="*", type=Path, default=[], help="exported timelines of candidates who bluffed")
    parser.add_argument("--genuine", nargs="*", type=Path, default=[], help="exported timelines of genuine attempts")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    files = [("bluff", p) for p in args.bluff] + [("genuine", p) for p in args.genuine]
    if not files:
        parser.error("give at least one --bluff or --genuine file")
    data, skipped = build(files)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    labels = [i["label"] for i in data["items"]]
    print(json.dumps({"written": str(args.out), "items": len(labels), "understands": labels.count("understands"),
                      "does_not_understand": labels.count("does_not_understand"), "left_out": skipped}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
