"""Run/replay the 30-clip realtime gate. Live mode is always explicit."""

import argparse
import asyncio
import csv
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time
import uuid

from claim_rules import ClaimTracker


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "probes"))
import probe_support as probes  # Reuse the verified WAV/PCM transport, without editing it.


class GateError(Exception):
    """Safe local validation error; never include provider exception text."""


def atomic_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def seconds(value):
    try:
        result = Fraction(str(value))
    except (ValueError, TypeError, ZeroDivisionError) as error:
        raise GateError("Time must be a finite number.") from error
    if result < 0:
        raise GateError("Time must be nonnegative.")
    return result


def validate_label(row):
    clip = row.get("clip", "")
    if (not isinstance(clip, str) or not clip or Path(clip).name != clip
            or "/" in clip or "\\" in clip or Path(clip).suffix.lower() != ".wav"):
        raise GateError("Each clip must be a WAV filename without a directory.")
    category = row.get("category", "")
    if category not in {"error", "non_error", "correct"}:
        raise GateError("Category must be error, non_error, or correct.")
    raw = str(row.get("should_fire", "")).lower().strip()
    if raw not in {"true", "false", "1", "0"}:
        raise GateError("should_fire must be true/false or 1/0.")
    should_fire = raw in {"true", "1"}
    if should_fire != (category == "error"):
        raise GateError("Only error clips may have should_fire=true.")
    return {"clip": clip, "category": category, "should_fire": should_fire,
            "claim_end_s": float(seconds(row.get("claim_end_s")))}


def load_labels(directory, path):
    if path.suffix.lower() != ".csv":
        raise GateError("Labels must be a .csv file; other file types are never read.")
    if not directory.is_dir():
        raise GateError("Recordings directory does not exist.")
    if not path.is_file():
        raise GateError("Labels CSV does not exist; create it using scripts/gate/README.md.")
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["clip", "category", "should_fire", "claim_end_s"]:
            raise GateError("CSV header must be clip,category,should_fire,claim_end_s.")
        labels = [validate_label(row) for row in reader]
    names = [row["clip"].casefold() for row in labels]
    if not labels or len(set(names)) != len(names):
        raise GateError("Labels must be nonempty and contain no duplicate clips.")
    wavs = {p.name.casefold(): p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".wav"}
    if set(names) != set(wavs):
        raise GateError("Labels must cover exactly every WAV directly in the recordings directory.")
    # Validate all input before spending credits. Never open raw/ or any non-WAV.
    for label in labels:
        _, info = probes.load_wav(wavs[label["clip"].casefold()])
        if seconds(label["claim_end_s"]) > seconds(info["duration_s"]):
            raise GateError("claim_end_s exceeds the WAV duration.")
        label["wav"] = info
        label["input_filename"] = wavs[label["clip"].casefold()].name
    return labels


def analyse_events(events):
    tracker = ClaimTracker()
    challenge = None
    for row in events:
        fired = tracker.consume(row)
        if fired is not None:
            # Live captures include the instant the rule evaluation completed.
            # Probe captures predate that field, so use their recorded arrival.
            decision = row.get("decision_elapsed_s", fired["challenge_elapsed_s"])
            if seconds(decision) < seconds(fired["challenge_elapsed_s"]):
                raise GateError("Decision time precedes its event arrival.")
            fired["challenge_elapsed_s"] = float(seconds(decision))
            challenge = fired
    return challenge


class GateRecorder(probes.Recorder):
    """Store private frames and run claim checks without printing raw transcripts."""

    def __init__(self, path, key):
        super().__init__("voice_realtime", path, key)
        self.tracker = ClaimTracker()
        self.challenge = None

    def accept(self, event, stream_elapsed_s, arrival_s, decision_clock=None):
        row = {
            "arrival_s": arrival_s, "stream_elapsed_s": stream_elapsed_s,
            "arrival_utc": datetime.now(timezone.utc).isoformat(),
            "event": probes.sanitize(event, self.key),
        }
        fired = self.tracker.consume(row)
        if stream_elapsed_s is not None:
            row["decision_elapsed_s"] = decision_clock() if decision_clock else stream_elapsed_s
        if fired:
            fired["challenge_elapsed_s"] = row["decision_elapsed_s"]
            self.challenge = fired
            self.data["challenge"] = fired
        self.data["events"].append(row)
        self.save()

    def event(self, event, stream_start):
        now = time.perf_counter()
        elapsed = None if stream_start is None else round(now - stream_start, 6)
        decision_clock = None if stream_start is None else lambda: round(time.perf_counter() - stream_start, 6)
        self.accept(event, elapsed, round(now - self.started, 6), decision_clock)


def clip_result(label, capture):
    label = validate_label(label)
    challenge = analyse_events(capture["events"])
    completed = capture.get("status") == "passed" and capture.get("close_code") == 1000
    result = {
        **label, "status": "passed" if completed else "failed",
        "challenge_fired": challenge is not None,
        "challenge_elapsed_s": None, "latency_s": None,
        "number_span": None, "claimed_value": None, "named_wrong": None,
        "error": capture.get("error"),
    }
    if challenge is not None:
        result.update({k: challenge[k] for k in ["challenge_elapsed_s", "number_span", "claimed_value", "named_wrong"]})
        result["latency_s"] = float(Fraction(str(challenge["challenge_elapsed_s"])) - seconds(label["claim_end_s"]))
    return result


def summarize(results):
    counts = {category: sum(row["category"] == category for row in results)
              for category in ["error", "non_error", "correct"]}
    unique = len({row["clip"].casefold() for row in results}) == len(results)
    complete = len(results) == 30 and counts == {"error": 10, "non_error": 10, "correct": 10} and unique
    transport_ok = bool(results) and all(row["status"] == "passed" for row in results)
    hits = sum(row["should_fire"] and row["challenge_fired"] for row in results)
    false = sum(not row["should_fire"] and row["challenge_fired"] for row in results)
    latencies = [Fraction(str(row["latency_s"])) for row in results
                 if row["should_fire"] and row["challenge_fired"] and row["latency_s"] is not None]
    median = statistics.median(latencies) if latencies else None
    maximum = max(latencies) if latencies else None
    criteria = {
        "complete_30_clip_set": complete, "all_transports_completed": transport_ok,
        "at_least_8_of_10_errors": hits >= 8, "zero_of_20_false_challenges": false == 0,
        "median_latency_at_most_1_5_s": median is not None and median <= Fraction(3, 2),
        "max_latency_at_most_3_s": maximum is not None and maximum <= 3,
    }
    return {
        "passed": all(criteria.values()), "criteria": criteria,
        "category_counts": counts, "errors_caught": hits, "false_challenges": false,
        "median_latency_s": None if median is None else float(median),
        "max_latency_s": None if maximum is None else float(maximum),
        "latency_sample_count": len(latencies),
    }


def write_outputs(directory, manifest):
    atomic_json(directory / "manifest.json", manifest)
    columns = ["clip", "category", "should_fire", "claim_end_s", "status", "challenge_fired",
               "challenge_elapsed_s", "latency_s", "number_span", "claimed_value", "named_wrong", "error"]
    with (directory / "results.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(manifest["results"])
    label = "OFFLINE REPLAY" if manifest["mode"] == "replay" else "LIVE GATE"
    summary = manifest["summary"]
    lines = [
        f"# Realtime gate — {label}", "",
        f"Run `{manifest['run_id']}`; recorded `{manifest['recorded_at']}`.", "",
        f"Result: **{'PASS' if summary['passed'] else 'FAIL / NOT PASSED'}**.", "",
        f"Errors caught: {summary['errors_caught']}/10. False challenges: {summary['false_challenges']}/20.",
        f"Median latency: {summary['median_latency_s']} s. Maximum: {summary['max_latency_s']} s.",
        f"Latency sample: {summary['latency_sample_count']} challenged error clips.", "",
    ]
    if manifest.get("source_run_id"):
        lines += [f"Source run `{manifest['source_run_id']}`, recorded `{manifest['source_recorded_at']}`.", ""]
    if manifest.get("error"):
        lines += [f"Run error: {manifest['error']}", ""]
    lines += ["| Criterion | Pass |", "| --- | --- |"]
    lines += [f"| {name} | {passed} |" for name, passed in summary["criteria"].items()]
    lines += ["", "| Clip | Category | Fired | Status | Latency (s) |",
              "| --- | --- | --- | --- | --- |"]
    for row in manifest["results"]:
        # Filenames are untrusted; JSON/CSV retain the exact value.
        clip = row["clip"].replace("|", "\\|").replace("\n", " ").replace("\r", " ")
        lines.append(f"| {clip} | {row['category']} | {row['challenge_fired']} | {row['status']} | {row['latency_s']} |")
    lines += ["", "Signed latency = challenge time from audio-stream start minus hand-labelled claim_end_s.",
              "No negative values are clamped. Audio processing progress is not the latency clock.",
              "Incomplete sets and transport failures cannot pass. No failed clips are silently omitted.",
              "This report does not update the decision log or establish the Tuesday public-link exit test.", ""]
    (directory / "report.md").write_text("\n".join(lines), encoding="utf-8")


async def live_clips(directory, labels, run_dir, manifest, key):
    for index, label in enumerate(labels):
        filename = f"clip-{index + 1:02d}.json"
        entry = {**label, "capture": filename}
        manifest["clips"].append(entry)
        atomic_json(run_dir / "manifest.json", manifest)
        recorder = GateRecorder(run_dir / filename, key)
        try:
            pcm, info = probes.load_wav(directory / label["input_filename"])
            if info != label["wav"]:
                raise GateError("WAV changed after preflight validation.")
            recorder.data["result"] = await probes.stream_wav(recorder, pcm, info, key)
            recorder.data["status"] = "passed"
        except asyncio.CancelledError:
            recorder.data.update(status="failed", error="Run interrupted.")
            raise
        except (GateError, probes.ProbeFailure) as error:
            recorder.data.update(status="failed", error=str(error))
        except Exception as error:
            recorder.data.update(status="failed", error=f"{type(error).__name__}; provider exception text omitted.")
        finally:
            recorder.save()
            entry["capture_sha256"] = hashlib.sha256((run_dir / filename).read_bytes()).hexdigest()
            manifest["results"].append(clip_result(label, recorder.data))
            manifest["summary"] = summarize(manifest["results"])
            write_outputs(run_dir, manifest)
        row = manifest["results"][-1]
        print(json.dumps({k: row[k] for k in ["clip", "status", "challenge_fired", "latency_s"]}), flush=True)


def replay_clips(source_path, run_dir, manifest):
    if source_path.suffix.lower() != ".json":
        raise GateError("Replay source must be a .json capture manifest.")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("kind") != "realtime_gate" or source.get("format_version") != 1:
        raise GateError("Source is not a version-1 realtime gate manifest.")
    manifest.update(source_run_id=source["run_id"], source_recorded_at=source["recorded_at"])
    seen = set()
    for index, entry in enumerate(source["clips"]):
        label = validate_label(entry)
        if label["clip"].casefold() in seen:
            raise GateError("Duplicate clip in replay manifest.")
        seen.add(label["clip"].casefold())
        name = entry["capture"]
        if Path(name).name != name or "/" in name or "\\" in name or not name.endswith(".json"):
            raise GateError("Capture must be a JSON filename within the source run.")
        raw = (source_path.parent / name).read_bytes()
        if entry.get("capture_sha256") and hashlib.sha256(raw).hexdigest() != entry["capture_sha256"]:
            raise GateError("Capture checksum differs from the original run.")
        capture = json.loads(raw)
        if capture.get("format_version") != 1 or capture.get("probe") != "voice_realtime":
            raise GateError("Unsupported realtime capture.")
        if seconds(label["claim_end_s"]) > seconds(capture["request"]["wav"]["duration_s"]):
            raise GateError("Claim annotation exceeds captured WAV duration.")
        local_name = f"clip-{index + 1:02d}.json"
        (run_dir / local_name).write_bytes(raw)
        manifest["clips"].append({**label, "capture": local_name,
                                  "capture_sha256": hashlib.sha256(raw).hexdigest()})
        manifest["results"].append(clip_result(label, capture))
    manifest["summary"] = summarize(manifest["results"])
    # Preserve a preflight/interruption error; replay must not turn it into a pass.
    if source.get("error") or source.get("status") in {"running", "failed"}:
        manifest["error"] = "Source run did not complete successfully; review its original manifest."
        manifest["summary"]["passed"] = False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=["live", "replay"])
    parser.add_argument("--recordings", type=Path, default=ROOT / "recordings" / "gate")
    parser.add_argument("--labels", type=Path, help="Default: <recordings>/labels.csv")
    parser.add_argument("--capture", type=Path, help="Source manifest.json for replay.")
    parser.add_argument("--run-dir", type=Path, help="New output directory, never overwritten.")
    args = parser.parse_args(argv)
    if args.mode == "replay" and args.capture is None:
        parser.error("replay requires --capture")
    run_id = uuid.uuid4().hex
    directory = args.run_dir or ROOT / "scripts" / "gate" / "runs" / run_id
    if directory.exists():
        parser.error("run-dir already exists; choose a new directory to preserve evidence")
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {
        "kind": "realtime_gate", "format_version": 1, "run_id": run_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "mode": args.mode,
        "rules_sha256": hashlib.sha256(Path(__file__).with_name("claim_rules.py").read_bytes()).hexdigest(),
        "status": "running", "clips": [], "results": [], "summary": summarize([]),
    }
    atomic_json(directory / "manifest.json", manifest)
    try:
        if args.mode == "replay":
            replay_clips(args.capture, directory, manifest)
        else:
            labels = load_labels(args.recordings, args.labels or args.recordings / "labels.csv")
            manifest["labels_snapshot"] = labels
            # A short set may be useful diagnostically, but is always FAIL/NOT PASSED.
            # All its labelled WAVs are still streamed and reported.
            atomic_json(directory / "manifest.json", manifest)
            try:
                key = os.environ["MODEL_API_KEY"]
            except KeyError as error:
                raise GateError("MODEL_API_KEY is missing from the process environment.") from error
            if not key.strip():
                raise GateError("MODEL_API_KEY is empty in the process environment.")
            asyncio.run(live_clips(args.recordings, labels, directory, manifest, key))
        manifest["status"] = "completed" if not manifest.get("error") else "failed"
    except (GateError, probes.ProbeFailure) as error:
        manifest.update(status="failed", error=str(error))
    except KeyboardInterrupt:
        manifest.update(status="failed", error="Run interrupted; inspect per-clip captures.")
    except Exception as error:
        manifest.update(status="failed", error=f"{type(error).__name__}; exception text omitted.")
    finally:
        manifest["summary"] = summarize(manifest["results"])
        if manifest.get("error"):
            manifest["summary"]["passed"] = False
        write_outputs(directory, manifest)
    label = "OFFLINE REPLAY" if args.mode == "replay" else "LIVE GATE"
    print(f"{label} run={run_id} recorded={manifest['recorded_at']}")
    print(json.dumps(manifest["summary"], indent=2))
    if manifest.get("error"):
        print(manifest["error"])
    print(f"Report: {directory / 'report.md'}")
    return 0 if manifest["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
