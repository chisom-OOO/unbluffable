"""Exploratory comparison, NOT pre-registered (decision log 47, registered before any call).

careful_first_only (the frozen careful prompt, shown only the original question and its
transcript) against unbluffable (the Exam Room's analysis of the original and the twin, and
the engine label), on the frozen run-1 items, Muse Spark 1.3, 3 runs each. Reported per
category: how many items each arm flags ("does_not_understand") by the majority of the runs,
and in each run, with the 10 recited items one by one. 39 of the 40 items are model-written.

The frozen prompts, harness.py, stats.py and the item file are used unchanged: this script
calls the harness's own functions and adds its two-arm plan at run time only. It refuses to
start with any of them, or itself, uncommitted, or with the item file's sha256 different.
Any failed call makes the run INVALID (reported as is; rerun once with the same command).

    python scripts/evidence/exploratory.py --items eval/items_draft.json \\
        --expect-items-sha256 b9aeb7f1dee995006df37c987f2c910cf781c4b3ddb9724df11ed8a90289a6d7
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness  # noqa: E402
import stats  # noqa: E402

DESIGN = "exploratory_first_only"
ARMS = ("careful_first_only", "unbluffable")
NAMES = {"careful_first_only": "Careful Muse Spark, first answer only", "unbluffable": "Unbluffable (original and new numbers)"}
CATEGORIES = (("memorised", "recited"), ("misconception", "misconception"), ("slip", "arithmetic slip"), ("correct", "correct"))
LABEL = "EXPLORATORY, not pre-registered (decision log 47, registered before any call); 39 of 40 items model-written"
CHECKED_PATHS = (*harness.FROZEN_PATHS, "scripts/evidence/exploratory.py", "eval/items_draft.json")


def register() -> None:
    """The two-arm plan, added to the harness at run time (harness.py itself is unchanged)."""
    harness.DESIGNS.setdefault(DESIGN, ARMS)


def report(items: list[dict], verdicts: dict[str, list[dict[str, str]]], provenance: dict, failures: list[dict]) -> dict:
    labels = {i["id"]: i["label"] for i in items}
    category = {i["id"]: i["category"] for i in items}
    out = {"label": LABEL, "status": harness.INVALID if failures else "complete", "provenance": provenance,
           "failures": harness.failure_summary(failures), "arms": {}}
    majority = {}
    for arm in ARMS:
        runs = verdicts[arm]
        majority[arm] = {i: stats.majority([run[i] for run in runs]) for i in labels}
        rows = {}
        for key, name in CATEGORIES:
            ids = [i for i in labels if category[i] == key]
            rows[key] = {
                "name": name, "items": len(ids),
                "flagged": sum(majority[arm][i] == stats.NOT_UNDERSTANDS for i in ids),
                "not_flagged": sum(majority[arm][i] == stats.UNDERSTANDS for i in ids),
                "no_verdict": sum(majority[arm][i] not in stats.LABELS for i in ids),
                "flagged_per_run": [sum(run[i] == stats.NOT_UNDERSTANDS for i in ids) for run in runs],
            }
        out["arms"][arm] = {"name": NAMES[arm], "categories": rows, "flips": stats.flips(runs),
                            "majority": majority[arm]}
    recited = [i["id"] for i in items if i["category"] == "memorised"]
    out["recited_items"] = [{"id": i, **{arm: majority[arm][i] for arm in ARMS}} for i in recited]
    if not failures:
        # Discordant recited items: b = Unbluffable flags and careful_first_only does not; c = the reverse.
        b = sum(majority["unbluffable"][i] == stats.NOT_UNDERSTANDS and majority["careful_first_only"][i] != stats.NOT_UNDERSTANDS for i in recited)
        c = sum(majority["careful_first_only"][i] == stats.NOT_UNDERSTANDS and majority["unbluffable"][i] != stats.NOT_UNDERSTANDS for i in recited)
        out["recited_mcnemar"] = {"b": b, "c": c, "p": stats.mcnemar_exact(b, c), "note": "exploratory, not pre-registered"}
    return out


def markdown(r: dict) -> str:
    p = r["provenance"]
    lines = [f"# {LABEL}", "",
             f"Status: **{r['status']}**. Items `{p['items_file']}` sha256 `{p['items_sha256']}`; {p['model']} ({p['backend']}); "
             f"{p['runs']} runs; commit `{p['git_commit']}`; {p['created_at']}.", "",
             "Items flagged (does_not_understand) by the majority of the runs; per run in brackets.", "",
             "| Category | Items | " + " | ".join(r["arms"][a]["name"] for a in ARMS) + " |",
             "| --- | --- | " + " | ".join("---" for _ in ARMS) + " |"]
    for key, name in CATEGORIES:
        cells = []
        for arm in ARMS:
            row = r["arms"][arm]["categories"][key]
            extra = f", {row['no_verdict']} no verdict" if row["no_verdict"] else ""
            cells.append(f"{row['flagged']} / {row['items']} ({', '.join(map(str, row['flagged_per_run']))}){extra}")
        lines.append(f"| {name} | {r['arms'][ARMS[0]]['categories'][key]['items']} | " + " | ".join(cells) + " |")
    lines += ["", "Recited items, majority verdict:", ""]
    lines += [f"- {row['id']}: careful_first_only {row['careful_first_only']}; unbluffable {row['unbluffable']}" for row in r["recited_items"]]
    for arm in ARMS:
        lines.append(f"\n{r['arms'][arm]['name']}: verdict changed across runs on {len(r['arms'][arm]['flips'])} item(s) {r['arms'][arm]['flips'] or ''}")
    if "recited_mcnemar" in r:
        m = r["recited_mcnemar"]
        lines.append(f"\nRecited items, exact McNemar (exploratory): Unbluffable only {m['b']}, careful_first_only only {m['c']}, p = {m['p']:.4g}")
    if r["status"] == harness.INVALID:
        lines.append(f"\nINVALID: {r['failures']['count']} failed call(s) {r['failures']['by_type']}; no test reported. Rerun once with the same command.")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    from llm import backends
    from voice.provider import MetaVoice

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--expect-items-sha256", required=True)
    parser.add_argument("--backend", choices=backends.BACKENDS, default="meta_api")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", type=Path, default=harness.ROOT / "eval" / "raw" / "exploratory-first-only")
    parser.add_argument("--record-dir", type=Path, default=harness.ROOT / "recordings" / "evidence-exploratory")
    args = parser.parse_args(argv)

    missing = harness.missing_keys([args.backend])
    if missing:
        print("Refusing to start: set " + ", ".join(missing) + " in the environment.")
        return 2
    dirty = harness.git("status", "--porcelain", "--", *CHECKED_PATHS)
    if dirty:
        print("Refusing to start: commit these first, so the run is reproducible from its commit:\n" + dirty)
        return 2
    items, sha = harness.load_items(args.items)
    if sha != args.expect_items_sha256:
        print(f"Refusing to start: item file hash {sha} is not the frozen {args.expect_items_sha256}.")
        return 2
    register()
    provider = MetaVoice("live", str(args.record_dir))
    provider.spark_backend = backends.get_backend(args.backend)
    prompts = harness.load_prompts()
    failures: list[dict] = []
    verdicts = asyncio.run(harness.evaluate(items, provider, args.runs, args.concurrency, prompts,
                                            design=DESIGN, failures=failures))
    results = report(items, verdicts, harness.provenance(args.items, sha, provider, args.runs, prompts, DESIGN), failures)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    (args.out / "results.md").write_text(markdown(results), encoding="utf-8")
    print(markdown(results))
    return 3 if results["status"] == harness.INVALID else 0


if __name__ == "__main__":
    raise SystemExit(main())
