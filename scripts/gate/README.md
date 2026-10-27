# Realtime gate harness

This harness implements the gate in `spec/03_ARCHITECTURE_AND_API.md`, including
the builder's clarification that stability applies to the **claimed number span**,
not the complete cumulative transcript. It uses exact `Fraction` arithmetic.
It does not run Spark, make product decisions, or update the gate decision log.

## Prepare the clips and labels

Put WAV files directly in `recordings/gate/`. Every WAV needs exactly one row in
`recordings/gate/labels.csv`, with this header and category vocabulary:

```csv
clip,category,should_fire,claim_end_s
E01.wav,error,true,8.1
N01.wav,non_error,false,4.2
C01.wav,correct,false,5.8
```

The rows above illustrate the format; their times are **not annotations** for any
existing recording. Label each clip's end of claim by hand, in seconds from the
start of the WAV. `should_fire` also accepts `1`/`0`. Categories are `error`
(committed wrong posterior), `non_error` (restated given/hypothetical/self-correction),
and `correct` (correct answer). The full set needs ten of each category. Duplicate
filenames, missing labels/WAVs, contradictory categories, nonfinite/negative times,
and claim ends beyond WAV duration are rejected before any API call.

WAVs must be mono 16-bit PCM, 16 or 24 kHz, positive duration, at most ten minutes
and 32 MB. Nested `raw/` files are not read. A smaller set can be run for diagnosis,
but its aggregate result is always **FAIL / NOT PASSED**.

## Run live

Run from the repo root with `MODEL_API_KEY` already in the process environment:

```powershell
.\.venv\Scripts\python.exe scripts/gate/run_gate.py --mode live --run-dir scripts/gate/runs/live-01
```

The key is accessed only through `os.environ["MODEL_API_KEY"]`. No environment
file is opened. Live mode is explicit. There are no automatic retries or package
installs. Each WAV uses a new realtime socket. The existing probe transport sends
authorization in the initial JSON frame, waits for acknowledgement, sends raw PCM
in 80 ms frames paced against a monotonic audio clock, sends `endStream`, and drains
pending events until a normal close. The harness continues across failed clips;
every failed transport makes the aggregate gate fail.

Routine terminal output contains per-clip fired/status/latency results, not raw
answers. Private captures contain all sanitized server events; authorization is
never stored. All generated files live in the git-ignored `scripts/gate/runs/`.
The original recordings stay in their existing ignored directory.

## Record and replay

Each output directory contains:

- `manifest.json`: run ID/date, mode, frozen labels and WAV PCM hashes, rule-code
  hash, capture checksums, per-clip results, and aggregate criteria.
- `clip-XX.json`: each clip's request settings, all server events, original arrival
  times, local decision times, and transport outcome, using the probe capture format.
- `results.csv`: one row per attempted clip, including fired/not fired, claimed
  number, stream-relative firing time, labelled claim end, and signed latency.
- `report.md`: gate pass/fail, criteria, and per-clip table.

Existing output directories are never overwritten. Choose a fresh directory each
time. Replay needs no key, audio, labels CSV, network, or realtime sleep:

```powershell
.\.venv\Scripts\python.exe scripts/gate/run_gate.py --mode replay --capture scripts/gate/runs/live-01/manifest.json --run-dir scripts/gate/runs/replay-01
```

Replay verifies capture checksums and **recomputes** claims and results from the
captured partials, original audio-relative arrival/decision times, and frozen labels.
It does not trust stored challenge results. It is labelled `OFFLINE REPLAY`, with
the source run ID/date. It uses the current rule code; the output stores that
code's hash, so retain the original manifest to compare versions. Incomplete or
failed source runs cannot pass. No live gate was run during implementation.

## Claim rules and timing

Recognized markers include “so the probability is”, “it's”, “I think/reckon/guess/
believe it's”, “I'd say ... is”, “I'd go with”, “I'd put it at”, “it comes out at/to”,
“the chance/odds (of fraud) is”, and “with probability”. Number-first commitments
include “X, that's my (final) answer”, “X is my answer”, and “X's my answer”.
Fillers “um”, “uh”, “er”, “like”, and “you know” may occur between marker words.

“The answer would be X” and “my answer would be X” are commitments. Other “would
be” constructions remain hypothetical, as do “suppose” and generic “if” clauses.
“If the alert goes off / if flagged / given a flag, it's X” remains a committed
conditional claim; an “if ... would be” construction remains hypothetical.

Givens, quoted/attributed answers (including “people say” and “my first instinct”),
negated commitments, questions, and corrections (“no”, “wait”, “actually”, “scratch
that”) suppress the current candidate. Given suffixes include “of fraud/genuine”,
“detection rate”, “false-alarm rate”, “specificity”, “base rate”, and “flagged”.
Incomplete suffixes such as “detection” defer judgment while the phrase grows.
Exclusions apply across the current cumulative turn, including trailing words;
punctuation alone does not clear them. Detector-rate subjects are also excluded.

For prefix commitments the latest marker must be followed immediately by a
parseable number (allowing approximation words). For number-first commitments,
the number must be adjacent to a completed answer suffix; its stability interval
starts when that suffix is observed. The parser supports digit/spoken
percentages, decimals, fractions with `over` or `/`, and ordinal fractions such as
“two thirteenths”. Bare “ninety”, “two over”, or “point” remains incomplete.
Bare integers above one await a percentage/fraction unit to avoid challenging an
unfinished numerator. Percentages/decimals use the spec/02 ±1 percentage-point
tolerance around `2/13`; explicit fractions require exact equality. Named wrong
values are `90%`, `95%`, `5%`, and `5.85%`; other committed wrong values also qualify.

A candidate must have the same number wording for the same claim occurrence across
at least two consecutive nonfinal transcript partials, and at least 500 ms must
elapse from its initial observed partial. Trailing words may grow, and unrelated
prefix wording may be revised. A number revision, removal, exclusion, new marker,
or turn boundary resets the interval. Equal values
with revised wording also reset it. Audio-progress events do not count as partials;
neither finals nor silence manufacture additional evidence. Evaluation happens
only on a received partial, without an independent timer. One challenge is retained
per clip; a later correction cannot erase an already-fired false challenge.

`challenge_elapsed_s` uses the monotonic clock from audio-stream start, including
local rule evaluation. It excludes connection/auth setup. `latency_s` is that
time minus the hand-labelled `claim_end_s`; it is signed and never clamped.
`audioProcessedMs` is processing progress, not an arrival clock or claim annotation.

The report passes only with all 30 valid completed clips, at least 8/10 errors
challenged, 0/20 false challenges, median latency at most 1.5 s, and maximum at
most 3 s. Latency statistics use challenged error clips only; missed errors remain
misses, and false challenges are counted independently. Thresholds are compared
without rounding. Exit code is `0` for gate pass, `1` for failure/incomplete run,
or `2` for command-line misuse. The Tuesday deadline and final recorded gate
decision remain the builder's responsibility under spec/03.

## Offline verification

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider scripts/gate/test_gate.py
```

The tests include synthetic adversarial partial sequences, number forms, exact
boundaries, turn handling, exclusion/revision resets, aggregate gate thresholds,
label validation, credential redaction, no-key/no-network replay, and regression
checks against the two existing realtime probe captures. Those two captures are
local ignored test inputs; they are not the 30-clip gate and have no invented
`claim_end_s` annotations. No raw recording is copied into a test fixture.

Verified on 27 October: **360 passed, 1 deselected** (1.41 s), with one existing
scaffold FastAPI/Starlette deprecation warning:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests scripts/probes/test_probes.py scripts/gate/test_gate.py -k "not live_probe_captures" --tb=short
```

The capture-based regression test was deliberately excluded for this update.
New tests use invented sentences for the four authorized failure types and near
misses, including growing partial givens and unchanged stability requirements.
Rules were frozen after those checks, before replaying only `live-02`. No other
recordings were inspected or used for tuning. No environment was modified.

## Replay of live-02 after the phrasing update

```powershell
.\.venv\Scripts\python.exe scripts/gate/run_gate.py --mode replay --capture scripts/gate/runs/live-02/manifest.json --run-dir scripts/gate/runs/replay-02b
```

Replay run `1df1a3d3c18445b2946ca1ee6b32204e`, 27 October, produced:

| Criterion | Result | Pass |
| --- | --- | --- |
| Committed errors challenged | 8/10 (previous live rules: 2/10) | Yes |
| False challenges | 0/20 | Yes |
| Median latency | 1.5274575 s | No; limit 1.5 s |
| Maximum latency | 2.127448 s | Yes; limit 3 s |
| Complete set / successful transports | 30 clips / 30 completed | Yes |

Overall: **FAIL / NOT PASSED**, exit code 1. This is a replay result, with no new
API calls. No rule changes were made after observing it. Thresholds, exact-number
checks, and the 500 ms/two-partial requirement are unchanged. Full captures and
per-clip reports remain local under ignored `runs/`; only these summaries are committed.

Monday exit evidence: the strict Spark probe is recorded as passing in the
capability sheet; pinned engine tests pass in the command above; the realtime
gate remains not passed because of median latency. The gate decision-log entry
has not been completed by this harness update.
