"""CLI for verified family packs, with at least 20 variants per family."""
import argparse
from decimal import Decimal
import hashlib
import json
import os
import re
from pathlib import Path

from forge.families import FamilyForge, load_families
from forge.models import DEFAULT_PRICES, Models, State, atomic_json
from forge.run import job_lock
from forge.packs import PACK_PREFIXES, output_prefix, pack_template_id
from forge.sandbox import Sandbox
from llm.backends import get_backend
from llm.client import MissingKey, _key

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--pack", choices=tuple(PACK_PREFIXES), default="quant")
    parser.add_argument("--prefix", default=None,
                        help="this batch's own file prefix (e.g. swf, qx, ibx, qd, swc); default: the pack's own")
    parser.add_argument("--mode", choices=("live", "replay"), default="replay")
    parser.add_argument("--budget-usd", type=Decimal, default=Decimal(5))
    parser.add_argument("--work-dir", type=Path, default=ROOT / "data" / "forge" / "families1")
    parser.add_argument("--recheck-families", default=None, help="Comma/space-separated family IDs; recheck cached drafts only, with no model calls")
    parser.add_argument("--retry-families", default=None, help="Comma/space-separated fallback family IDs to author again under the current prompt")
    parser.add_argument("--price", action="append", default=[], metavar="BACKEND=INPUT,OUTPUT")
    parser.add_argument("--timeout-s", type=float, default=10)
    parser.add_argument("--memory-mb", type=int, default=128)
    args = parser.parse_args(argv)
    recheck_ids = [value for value in re.split(r"[,\s]+", (args.recheck_families or "").strip()) if value]
    if args.recheck_families is not None and not recheck_ids:
        parser.error("--recheck-families must contain at least one family ID")
    retry_ids = [value for value in re.split(r"[,\s]+", (args.retry_families or "").strip()) if value]
    if args.retry_families is not None and not retry_ids:
        parser.error("--retry-families must contain at least one family ID")
    if not args.work_dir.resolve().is_relative_to((ROOT / "data" / "forge").resolve()):
        parser.error("--work-dir must stay inside ignored data/forge")
    if args.csv.suffix.casefold() != ".csv" or any(part.casefold() in {".env", "captures", "recordings"} for part in args.csv.parts):
        parser.error("Input must be a CSV, never an environment file or capture")
    if any(args.csv.resolve().is_relative_to(ROOT / "scripts" / kind / "runs") for kind in ("gate", "probes")):
        parser.error("Capture folders are not family input")
    if not args.budget_usd.is_finite() or not 0 <= args.budget_usd <= 5:
        parser.error("Family budget must be between zero and five USD")
    try:
        output_prefix(args.pack, args.prefix)
    except ValueError:
        parser.error("--prefix: 2-8 lowercase letters or digits, not \"family\" or another pack's prefix")
    try:
        prices = dict(DEFAULT_PRICES)
        for flag in args.price:
            backend, values = flag.split("=", 1)
            pair = values.split(",")
            if backend not in prices or len(pair) != 2:
                raise ValueError("Invalid price")
            prices[backend] = tuple(pair)
        author = get_backend(os.environ.get("LLM_BACKEND", "open_weights"))
        if author.name != "open_weights":
            raise ValueError("Family author must use open_weights")
        if args.mode == "live":
            _key("BASETEN_API_KEY")
        signature = hashlib.sha256(args.csv.read_bytes()).hexdigest()
        families = load_families(args.csv)
        if hashlib.sha256(args.csv.read_bytes()).hexdigest() != signature:
            raise ValueError("Source changed while loading")
        with job_lock(args.work_dir):
            state = State(args.work_dir)
            if state.data.setdefault("csv_sha256", signature) != signature:
                raise ValueError("Use a new work directory for a changed CSV")
            # Never overwrite a family file this work directory did not make (a new batch takes its own --prefix).
            clash = sorted(tid for tid in (pack_template_id(args.pack, f.family_id, args.prefix) for f in families)
                           if (ROOT / "content" / "forge" / f"{tid}.json").exists() and tid not in state.data.get("items", {}))
            if clash:
                print(json.dumps({"status": "would_overwrite", "files": clash[:20], "count": len(clash),
                                  "fix": "use a new --prefix for this batch"}))
                return 1
            models = Models(state, mode=args.mode, budget_usd=args.budget_usd, prices=prices, author=author)
            forge = FamilyForge(models, output=ROOT / "content" / "forge", funnel=args.work_dir / "funnel.json",
                                sandbox=Sandbox(args.timeout_s, args.memory_mb), pack=args.pack, prefix=args.prefix)
            report = forge.run(families, recheck_families=recheck_ids, retry_families=retry_ids)
            if args.pack == "quant":
                atomic_json(ROOT / "forge" / "funnel.json", report)
    except (OSError, ValueError, ArithmeticError, MissingKey) as error:
        # Exception bodies can contain source text or filesystem details.
        print(json.dumps({"status": "configuration_error", "type": type(error).__name__}))
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
