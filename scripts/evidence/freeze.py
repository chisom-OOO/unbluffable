"""Freeze the evidence items (decision log 15): validate the file, refuse empty or
off-category transcripts, then print its sha256 and the exact harness command.

  python scripts/evidence/freeze.py [--items eval/items_draft.json]

Nothing is changed or sent. Commit the item file before the live run; the harness
refuses to run if the file's hash differs from the one printed here.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness  # noqa: E402
import itemcheck  # noqa: E402


def freeze(path: Path) -> tuple[bool, list[str], str]:
    try:
        items, digest = harness.load_items(path)  # refuses empty transcripts and bad instances
    except (harness.ItemError, ValueError, OSError) as error:
        return False, [str(error)], ""
    found = itemcheck.problems(items)
    return not found, found, digest


def command(path: Path, digest: str) -> str:
    try:
        shown = path.resolve().relative_to(itemcheck.ROOT).as_posix()
    except ValueError:
        shown = str(path)
    return (f"python scripts/evidence/harness.py --items {shown} --backend meta_api --runs 3 "
            f"--expect-items-sha256 {digest}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--items", type=Path, default=itemcheck.DRAFT)
    args = parser.parse_args(argv)
    ok, found, digest = freeze(args.items)
    if not ok:
        print(f"Not frozen: {len(found)} problem{'s' if len(found) != 1 else ''}.")
        for line in found:
            print(f"  - {line}")
        return 1
    print(f"Frozen: {args.items}")
    print(f"sha256 {digest}")
    print(f"Slip items are labelled {itemcheck.SLIP_LABEL!r}.")
    print("Live run (4 arms x 3 runs x 40 items):")
    print(f"  {command(args.items, digest)}")
    print("With the careful arm and Unbluffable also on Muse Spark Open (separate rows):")
    print(f"  {command(args.items, digest)} --open-weights")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
