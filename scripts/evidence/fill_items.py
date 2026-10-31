"""Type or paste the evidence transcripts (decision log 15), one item at a time.

Each transcript is checked against its item's category with exact maths before it is
kept (see itemcheck.py). The file is saved after every item, so you can stop with
Ctrl+C and run again to carry on from the first unfinished item.

  python scripts/evidence/fill_items.py [--items eval/items_draft.json] [--redo e07]

For each transcript, paste it and finish with a line containing only "." (a blank line
inside the text is fine). Type "skip" to leave an item for later, "quit" to stop.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import itemcheck  # noqa: E402

SOURCE_KEYS = {"b": "builder", "t": "tester", "m": "model-written"}


class Stop(Exception):
    pass


class Skip(Exception):
    pass


def read_block(ask) -> str:
    """Lines until a lone "."; "skip" or "quit" on the first line."""
    lines = []
    while True:
        line = ask("" if lines else "> ")
        if not lines and line.strip().lower() in ("quit", "q"):
            raise Stop
        if not lines and line.strip().lower() == "skip":
            raise Skip
        if line.strip() == ".":
            return "\n".join(lines).strip()
        lines.append(line)


def ask_source(ask, current: str) -> str:
    while True:
        hint = f" [{current}]" if current else ""
        answer = ask(f"Source: (b)uilder, (t)ester or (m)odel-written{hint}: ").strip().lower()
        if not answer and current:
            return current
        if answer in ("quit", "q"):
            raise Stop
        if answer in SOURCE_KEYS or answer in SOURCE_KEYS.values():
            return SOURCE_KEYS.get(answer, answer)
        print("  Please type b, t or m.")


def fill(path: Path, ask=input, redo: str | None = None) -> int:
    items = itemcheck.read(path)
    if redo:
        for item in items:
            if item["id"] == redo:
                item["original"]["transcript"] = item["twin"]["transcript"] = ""
    todo = [i for i in items if not (i["original"]["transcript"].strip() and i["twin"]["transcript"].strip() and i.get("source"))]
    print(f"{len(items) - len(todo)} of {len(items)} items done.")
    try:
        for item in todo:
            print(f"\n=== {item['id']} · {item['category']} · {item['topic']} ({item['difficulty']}) ===")
            try:
                for part in ("original", "twin"):
                    if item[part]["transcript"].strip() and itemcheck.check(item, part, item[part]["transcript"])[0]:
                        continue
                    print(f"\n{part.title()} question:\n  {item[part]['question']['text']}")
                    print(f"It should commit to {itemcheck.target(item, part)}.")
                    while True:
                        text = read_block(ask)
                        ok, why = itemcheck.check(item, part, text)
                        print(("  OK: " if ok else "  Not accepted: ") + why)
                        if ok:
                            item[part]["transcript"] = text
                            break
                item["source"] = ask_source(ask, item.get("source", ""))
            except Skip:
                print("  Skipped for now.")
                continue
            itemcheck.write(path, items)  # after every item
            print(f"  Saved {item['id']}.")
    except (Stop, EOFError, KeyboardInterrupt):
        itemcheck.write(path, items)
        print("\nStopped; saved. Run again to carry on.")
    left = [i["id"] for i in items if i.get("source") not in itemcheck.SOURCES
            or not all(itemcheck.check(i, part, i[part]["transcript"])[0] for part in ("original", "twin"))]
    print(f"\n{len(items) - len(left)} of {len(items)} items ready." + (f" Still to do: {', '.join(left)}" if left else ""))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--items", type=Path, default=itemcheck.DRAFT)
    parser.add_argument("--redo", default=None, help="clear one item's transcripts and fill it again")
    args = parser.parse_args(argv)
    return fill(args.items, redo=args.redo)


if __name__ == "__main__":
    raise SystemExit(main())
