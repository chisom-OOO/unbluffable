"""Read-only, content-aware gate replay. Never print or copy captured speech.

Run with this worktree's Python: -m voice.acceptance --mode replay --records PATH.
Live mode records Spark decisions outside the repository, never in the captures.
"""

import argparse
import asyncio
import json
from pathlib import Path
import tempfile

from voice.endpointing import classify
from voice.provider import MetaVoice
from voice.recording import VoiceError
from voice.turns import AnswerMerger


async def replay_clip(rows, provider):
    events = [(row.get("stream_elapsed_s", row.get("elapsed_s")), row["event"]) for row in rows]
    events = [(elapsed, event) for elapsed, event in events if elapsed is not None]
    speech = [(elapsed, event) for elapsed, event in events
              if event.get("type") in {"speechStart", "speechEnd", "speechComplete", "transcript"}]
    final_boundary = max((elapsed for elapsed, event in speech if event.get("type") == "speechEnd"), default=0)
    finals = {}
    for _, event in speech:
        if event.get("type") == "speechStart":
            finals.setdefault(event["turnId"], "")
        if event.get("type") == "speechComplete":
            finals[event["turnId"]] = event.get("transcript", "")
    expected = " ".join(value.strip() for value in finals.values() if value.strip())
    merger = AnswerMerger()
    index, now, pending, missing = 0, 0, None, False
    last_cue = "no_speech"
    limit = (events[-1][0] if events else 0) + 8.1
    while now <= limit:
        # Arrivals win ties, as a new partial invalidates an in-flight decision.
        while index < len(events) and events[index][0] <= now:
            elapsed, event = events[index]
            merger.feed(event, elapsed)
            index += 1
        if pending and pending[1] != merger.revision:
            pending = None
        if pending and pending[0] <= now:
            _, _, decision = pending
            pending = None
            last_cue = decision.cue
            if decision.finished:
                # The production relay drains final hypotheses after endStream.
                # Never treat that drain as permission to accept later speech.
                early = now < final_boundary
                # Drain only finals of turns already seen, just as endStream
                # does. Future candidate speech must never be swept into a pass.
                for _, event in events[index:]:
                    if event.get("type") == "speechComplete" and event["turnId"] in merger.turns:
                        merger.feed(event, now)
                try:
                    answer = merger.finish(decision.cue)
                except ValueError:
                    answer = None
                complete = bool(answer) and bool(expected) and answer["transcript"] == expected
                once = bool(answer) and merger.finish(decision.cue) is None
                return {"passed": not early and complete and once and not missing,
                        "completions": int(bool(answer)), "early": early,
                        "cue": "model_unavailable" if missing and not early else decision.cue,
                        "boundary_cue": decision.cue, "at_s": round(now, 3),
                        "model_unavailable": missing}
        if pending is None and merger.remaining(now) == 0:
            merger.checked_revision = merger.revision
            try:
                decision = await classify(provider, merger.transcript)
                pending = (now + decision.latency_s, merger.revision, decision)
                limit = max(limit, pending[0] + .1)
            except VoiceError:
                missing = True
                last_cue = "model_unavailable"
            if pending and pending[0] <= now:
                continue
        if merger.prompt_remaining(now) == 0:
            merger.prompted_revision = merger.revision
        choices = [limit + 1]
        if index < len(events):
            choices.append(events[index][0])
        if pending:
            choices.append(pending[0])
        for delay in (merger.remaining(now), merger.prompt_remaining(now)):
            if delay is not None and delay > 0:
                choices.append(now + delay)
        now = min(choices)
    return {"passed": False, "completions": 0, "early": False, "cue": last_cue,
            "model_unavailable": missing}


async def run(root, provider):
    results = []
    for run_id in ("live-02", "live-03"):
        manifest = json.loads((root / run_id / "manifest.json").read_text(encoding="utf-8"))
        for clip in manifest["clips"]:
            name = Path(clip["capture"]).name
            captured = json.loads((root / run_id / name).read_text(encoding="utf-8"))
            result = await replay_clip(captured["events"], provider)
            row = {"clip": f"{run_id}/{name}", **result}
            results.append(row)
            print(json.dumps(row), flush=True)
    print(json.dumps({"passed": sum(row["passed"] for row in results), "total": len(results),
                      "early": sum(row["early"] for row in results),
                      "model_unavailable": sum(row["model_unavailable"] for row in results)}))
    return all(row["passed"] for row in results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, default=Path(r"C:\Users\chiso\unbluffable\scripts\gate\runs"))
    parser.add_argument("--mode", choices=("live", "replay"), default="replay")
    parser.add_argument("--records", type=Path, default=Path(tempfile.gettempdir()) / "unbluffable-turn-taking")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parent.parent
    # Model requests include transcripts. Keep acceptance records out of both
    # worktrees and protect the original captures from any writes.
    for protected in (repository, args.capture_root.resolve().parents[2]):
        if args.records.resolve().is_relative_to(protected):
            parser.error("Acceptance model records must be outside the repository and source worktree.")
    return 0 if asyncio.run(run(args.capture_root, MetaVoice(args.mode, args.records))) else 1


if __name__ == "__main__":
    raise SystemExit(main())
