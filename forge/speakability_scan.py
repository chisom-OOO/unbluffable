"""Speakability scan over every spoken family in content/forge (engine.speakability).

A variant is flagged for a list, brackets, a tuple, a subscript or underscore, "proportional
to [", more than 6 numbers, more than 60 words (only with none of those), or jargon ("toy payoff", "fill indicator").
Coding-round families (sw_, swf_, qd_) are exempt: never removed (the interviewer says
the problem is on screen). Any other family where most variants (more than half) are flagged
leaves the spoken interview pool,
except that no topic may end up empty: then its least-bad family (fewest flagged variants,
then fewest flags) stays, and the report says so.

Writes engine/unspoken.json (what Bank.pool() skips; delete an id to restore a family) and
prints removed families per track and the families left per topic. Pure: no model calls.

    .venv/Scripts/python -m forge.speakability_scan            # report and write
    .venv/Scripts/python -m forge.speakability_scan --dry-run  # report only
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from engine import mathtext, speakability
from engine.bank import DEFAULT_DIR, UNSPOKEN_FILE, ForgeTemplate, load_bank


def family_report(template: ForgeTemplate) -> dict:
    reasons = [speakability.flags(mathtext.display(i.text)).reasons for i in template.instances]
    flagged = sum(1 for r in reasons if r)
    counts = Counter(r.split(":")[0] if r.startswith("jargon") else ("numbers" if r.endswith(" numbers") else
                     "words" if r.endswith(" words") else r) for rs in reasons for r in rs)
    return {"pack": template.pack, "topic": template.topic, "variants": len(reasons), "flagged": flagged,
            "flags": sum(len(r) for r in reasons), "reasons": dict(sorted(counts.items()))}


def scan(directory: Path | str | None = None) -> dict:
    bank = load_bank(directory or DEFAULT_DIR, hidden=frozenset())
    families = {tid: family_report(t) for tid, t in sorted(bank.templates.items())}
    mostly = {tid for tid, f in families.items()
              if f["flagged"] * 2 > f["variants"] and not speakability.coding_family(tid)}
    kept: dict[str, dict] = {}
    by_topic: dict[tuple[str, str], list[str]] = {}
    for tid, f in families.items():
        by_topic.setdefault((f["pack"], f["topic"]), []).append(tid)
    for (pack, topic), ids in by_topic.items():
        if all(tid in mostly for tid in ids):
            best = min(ids, key=lambda t: (families[t]["flagged"] / families[t]["variants"], families[t]["flags"], t))
            kept[best] = {**families[best], "why": f"the only way to keep {topic} ({pack}) non-empty"}
    hidden = {tid: families[tid] for tid in sorted(mostly) if tid not in kept}
    remaining: dict[str, dict[str, int]] = {}
    for (pack, topic), ids in sorted(by_topic.items()):
        remaining.setdefault(pack, {})[topic] = sum(1 for t in ids if t not in hidden)
    return {"families": families, "hidden": hidden, "kept_least_bad": kept, "remaining": remaining}


def report(result: dict) -> str:
    lines = []
    for pack in result["remaining"]:
        gone = [(tid, f) for tid, f in result["hidden"].items() if f["pack"] == pack]
        total = sum(1 for f in result["families"].values() if f["pack"] == pack)
        lines.append(f"## {pack}: {len(gone)} of {total} families removed from the spoken pool")
        for tid, f in gone:
            lines.append(f"- {tid} ({f['topic']}): {f['flagged']}/{f['variants']} variants flagged; "
                         + ", ".join(f"{k} {v}" for k, v in f["reasons"].items()))
        for tid, f in result["kept_least_bad"].items():
            if f["pack"] == pack:
                lines.append(f"- KEPT {tid} ({f['topic']}): {f['flagged']}/{f['variants']} flagged, {f['why']}")
        lines.append("Families left per topic: " + "; ".join(f"{t} {n}" for t, n in result["remaining"][pack].items()))
        lines.append("")
    return "\n".join(lines)


def write(result: dict, path: Path = UNSPOKEN_FILE) -> None:
    keep = lambda f: {k: f[k] for k in ("pack", "topic", "variants", "flagged", "reasons")}  # noqa: E731
    path.write_text(json.dumps({
        "about": "Families kept out of the spoken interview pool (forge/speakability_scan.py); most of their "
                 "variants are hard to follow by ear. Remove an id to put a family back.",
        "hidden": {tid: keep(f) for tid, f in result["hidden"].items()},
        "kept_least_bad": {tid: {**keep(f), "why": f["why"]} for tid, f in result["kept_least_bad"].items()},
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", default=None, help="forge directory (default content/forge)")
    parser.add_argument("--dry-run", action="store_true", help="report only; don't write engine/unspoken.json")
    args = parser.parse_args(argv)
    result = scan(args.dir)
    print(report(result))
    if not args.dry_run:
        write(result)
        print(f"wrote {UNSPOKEN_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
