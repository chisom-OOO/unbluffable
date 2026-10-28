# Hands-free voice path

Decision log 4 replaces the fixed silence boundary. `/practice` remains a fixed
flagship practice page; this change does not add the remaining interview packs.

After consent, **Start interview** requests the microphone and starts browser
speech in the same gesture. Questions, acknowledgements, challenges and silence
prompts speak automatically. The mic and audio worklet stay open until Stop;
the server opens the next transcription session while scoring runs. Done flushes
pending samples and finishes the current answer, while capture remains available
for the next one. File upload, local file recording and typed input remain available.

Without **Using headphones**, browser speech mutes both the microphone track and
the PCM worklet. With the toggle on, provider `speechStart` cancels browser speech.
Microphone capture requests echo cancellation and noise suppression. Muting the
interviewer keeps the displayed text and lets the candidate continue by voice.

## Content boundaries

Each provider turn end, or 0.8 seconds without a new partial, requests a content
check; a pause alone never finishes an answer. General cues handle explicit
closers, simple help/clarify requests, trailing fillers, unfinished clauses and
explicit requests for thinking time. Other cases use Standard Muse Spark at
`minimal` effort with exactly two strict fields:

```json
{"finished": false, "kind": "thinking"}
```

`kind` is `answer`, `question`, `help` or `thinking`. Thinking always keeps listening,
even if a model inconsistently returns `finished: true`. New speech or revisions
invalidate an in-flight result. No retry is made for an unchanged transcript. Model
errors keep listening. After eight seconds without activity the interviewer asks
**Want to talk me through where you are?** once per quiet period, without scoring.
The timer pauses during interviewer speech without headphones.

The server sends `endStream` only for an accepted content boundary or Done, drains
final hypotheses, then emits one `answer_complete`. A meaningful final revision
must also pass content detection. Unexpected provider closure does not complete
an answer. Cumulative partials replace earlier text within their turn; delayed
finals do not overwrite a newer turn.

`VOICE_PARTIAL_IDLE_SECONDS` can adjust the partial-idle content-check delay
(default 0.8); it is not an automatic answer-completion threshold.

## Run and replay

Use this worktree's existing `.venv` with the key already in the server environment:

```powershell
$env:VOICE_MODE = "live"
$env:DATABASE_PATH = "recordings/voice/events.sqlite3"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Microphone access needs HTTPS or localhost. Browser speech is disclosed on screen.
The server uses `os.environ["MODEL_API_KEY"]`, authenticates realtime transcription
in its initial JSON frame and never sends a key to the browser. No environment file
is read by this code.

Every live ASR, endpoint, challenge and scoring call uses the private record store
(`VOICE_RECORD_DIR`, default `recordings/voice`). Spark calls have strict schemas,
a 4,000-token cap and reject truncated/refused output. Full scoring uses `low`;
endpoint and challenge calls use `minimal`. Audio never goes to Spark.

For no-key replay set `VOICE_MODE=replay` and point `VOICE_RECORD_DIR` at successful
existing records. Realtime replay reproduces the recorded capture boundary;
challenge, scoring and endpoint replay match exact recorded requests. Missing
records produce an error, never a fabricated result. File replay matches the
uploaded source hash without invoking ffmpeg. Live file conversion uses ffmpeg
(`FFMPEG_BIN` optionally selects it) and always waits for transcript confirmation.

## Acceptance and verification

The separate acceptance runner reads the original 60 event streams without
printing transcripts or writing into the source captures. It simulates provider
boundaries and 0.8-second partial-idle checks, incorporates recorded model latency,
invalidates stale decisions, and checks for one completion at a valid semantic
boundary. A committed answer, question, help request or explicit closer permits
completion even when speech continues later; an unfinished thought does not.
The last provider speech boundary and equality with the full clip transcript are
not acceptance requirements. Ambiguous content relies on the recorded endpoint
decision; this is not an independent human-labelled check of model accuracy.
Output contains only clip IDs, timing, counts and decision cues. A missing
model result fails acceptance; a longer silence window or forced Done cannot pass it.

```powershell
.\.venv\Scripts\python.exe -m voice.acceptance --mode replay
```

Its default records live outside both worktrees, in the system temporary directory
under `unbluffable-turn-taking`. For a live acceptance run with an available server
key, run this command from the worktree; every endpoint-model response is recorded
outside both repositories:

```powershell
.\.venv\Scripts\python.exe -m voice.acceptance --mode live --capture-root "C:\Users\chiso\unbluffable\scripts\gate\runs" --records "$env:TEMP\unbluffable-turn-taking"
```

`MODEL_API_KEY` must already be exported in that PowerShell session. Re-run with
`--mode replay` to verify keyless reproduction. `--records PATH` selects an existing
external store. Records containing private gate text must never go into the repo.
The source worktree's `live-02` and `live-03` captures are read only.

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests scripts/probes/test_probes.py scripts/probes/test_spark_latency.py --tb=short
```

Synthetic tests cover content cues, the strict model contract and keyless replay,
stale decisions, long thinking pauses, prompts and final-transcript draining.
The Node unit checks run through pytest and cover Start, continuous capture,
headphone barge-in, speaker muting, stale speech callbacks, PCM and Done flushing.
Private merging tests do not print or copy speech. They are separate from acceptance.

The public-link exit tests in spec/04 still require a deployed service and real
microphone/browser validation. Unit tests are not evidence that those checks pass.

## Endpoint stage telemetry

Live `endpoint_decision` events and server log entries include a `decision_id`,
`phase`, `cue`, `kind`, `finished` and `timing_ms`. The decision ID joins the
decision, endStream, final-transcript and browser updates for one check. Every
stage is in milliseconds from the last non-final partial received by the server:

- `last_partial_received` (zero)
- `partial_idle_fired` (the actual timer firing time)
- `endpoint_decision_started` and `endpoint_decision_finished`
- `end_stream_sent`
- `final_transcript_received` (latest speechComplete arrival, possibly before endStream)
- `acknowledgement_audio_first_byte`
- `checking_working_shown` (the browser status DOM update)
- `acknowledgement_speech_started` (the browser SpeechSynthesis `onstart` callback)

Unobserved or bypassed stages are null. In particular, a provider speech boundary
can trigger the existing content check without the partial-idle timer firing.
Done bypasses the content decision. A run with no non-final partial has no timing
origin. These cases do not invent an 800 ms wait.

Browser SpeechSynthesis exposes no audio bytes, so
`acknowledgement_audio_first_byte` remains null with
`audio_first_byte_status=unavailable_browser_speech_synthesis`. Speech start is a
separate observable, not an audio-first-byte measurement. Browser stage times
are anchored to answer_complete receipt using performance.now; they exclude that
frame's network transit time. `browser_clock` explicitly identifies this estimate.
The browser posts only the timing snapshot to `/api/voice/timing`; the server
allowlists numeric stages, cue/kind enums and the decision ID before logging.
Neither this event nor its routine log entry includes transcript text or keys.

To inspect a live run, use a shell where MODEL_API_KEY is already exported:

```powershell
$env:VOICE_RECORD_DIR = Join-Path $env:TEMP 'unbluffable-turn-timing'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info
```

Open http://127.0.0.1:8000/practice, consent, Start, and say the test answer once.
Inspect the `endpoint_decision` log entries, especially `phase=browser` for the
combined server stages and acknowledgement/UI observations. Private live model
records go to the external directory above; the diagnostic log has no answer text.

### Validation on 27 October

The pytest command above passes **397 tests** (one existing Starlette deprecation
warning). This includes the engine pinned tests, synthetic content detection,
continuous websocket capture, browser controller checks and mocked keyless replay.

The acceptance replay command exits 1: **0/60 accepted**, with endpoint-model
records unavailable for every `live-02/clip-01.json` through `clip-30.json` and
`live-03/clip-01.json` through `clip-30.json`. These captures contain ASR events,
not responses to the new endpoint schema. A key or matching external endpoint
records is still needed to verify the model-backed detector.

After the builder's semantic-criterion clarification, the replay reports **zero
early completions**. **live-02/clip-10.json**, **7.984 s**, cue **explicit_closer**,
is a permitted completion even though speech follows. All 60 clips remain
unverified because endpoint-model records are missing. The detector's cue rules
and model prompt were not changed. No recorded speech was copied into the
repository or printed. No live model calls were made in this session.

The updated acceptance unit tests pass **10/10**:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_voice_acceptance.py --tb=short
```

Spec/04 status: Monday's offline engine checks pass; Tuesday's public-link
challenge/non-challenge exit test and Wednesday's complete voice interview remain
unverified. No public deployment or real-browser microphone check was performed.
