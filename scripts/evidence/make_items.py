"""Draft the 40 evidence items (decision log 15): question pairs from Quant forge families
with verified misconceptions, an interview-friendly original, and the engine's own twin
choice (aimed at the item's misconception for that category). Transcripts are empty:
fill them with fill_items.py, then freeze.py. No model calls.

  python scripts/evidence/make_items.py [--out eval/items_draft.json] [--force]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import itemcheck  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=itemcheck.DRAFT)
    parser.add_argument("--seed", type=int, default=itemcheck.SEED)
    parser.add_argument("--force", action="store_true", help="overwrite a draft that already has transcripts")
    args = parser.parse_args(argv)
    if args.out.exists() and not args.force:
        filled = sum(bool(i[p]["transcript"].strip()) for i in itemcheck.read(args.out) for p in ("original", "twin"))
        if filled:
            print(f"{args.out} already has {filled} transcripts; use --force to start again.")
            return 1
    items = itemcheck.make_items(seed=args.seed)
    itemcheck.write(args.out, items)
    print(f"Wrote {len(items)} items to {args.out}")
    print(f"  categories: {dict(Counter(i['category'] for i in items))}")
    print(f"  families: {len({i['template_id'] for i in items})}, topics: {len({i['topic'] for i in items})}")
    print(f"  slip items are labelled {itemcheck.SLIP_LABEL!r} (confirm before the freeze)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
