# After-turn voice path

Decision-log rows 1/1a/1b are final: partials update the live transcript, and no
challenge is evaluated until the complete answer has been assembled. This branch
adds a fixed flagship practice page at `/practice`; it does not implement the
remaining multi-question interview UI or deploy a public service.

## Run

Use this checkout's existing environment. No installation or environment creation
is performed by the voice code. The server needs the already-installed runtime
dependencies (`httpx`, `websockets`) and ffmpeg for file conversion.

With `MODEL_API_KEY` already exported in this PowerShell window:

```powershell
$env:VOICE_MODE = "live"
$env:VOICE_SILENCE_SECONDS = "1.8"
$env:DATABASE_PATH = "recordings/voice/events.sqlite3"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/practice`. Microphone capture requires HTTPS or
localhost. The key is read only with `os.environ["MODEL_API_KEY"]`, added on the
server, and never placed in the page, a URL, a routine log, or a browser message.
No environment file is opened.

The page supports live microphone transcription, local browser recording followed
by file transcription, audio-file upload, and typed answers. File transcription
always waits for the user to edit/confirm the transcript before either Spark call.
The interviewer uses browser speech with a mute toggle; microphone PCM is muted
while speech plays. A browser without live PCM support can use file or text input.

## Completion and parallel checks

The browser sends mono 16-bit PCM at 16 kHz in 80 ms frames. The relay paces frames,
authenticates in the initial JSON frame, and uses Muse Voice Transcribe in
`ENDPOINTING`/`CUMULATIVE` mode. Each partial replaces its turn's earlier hypothesis.
Turn IDs preserve order and keep delayed finals from overwriting a newer turn.
Repeated final messages replace the same turn rather than duplicating its text.

Consecutive speech turns remain one answer until `VOICE_SILENCE_SECONDS` of silence
(default **1.8 s**), or a client `{"type":"done"}` message. The Done button flushes
pending microphone samples before sending that control. Both completion paths end
provider input with `endStream`, drain pending final text, and emit exactly one
`answer_complete`. A turn with no final transcript is not scored as a partial.

The app sends `answer_complete` with **“Okay, let me check your working”** before
scheduling either Spark task. The browser immediately clears stale speech and
enqueues that acknowledgement. The two independent jobs then run concurrently:

- Challenge: `muse-spark-1.3`, `reasoning_effort="minimal"`, the two-field strict
  schema from the latency probe. The model identifies a committed number; exact
  `Fraction` normalization and `engine.answers.matches` decide whether it is wrong.
- Scoring: the full spec/03 extraction schema at `reasoning_effort="low"`. Quotes
  not found verbatim are dropped; missing quoted reasoning cannot support Correct.
  `engine.coding.code_answer` creates the observation, so a wrong number cannot be
  scored Correct. Natural-frequency calculations are explicitly defined as actual
  reasoning rather than hypothetical steps.

Both use Standard IDs, explicit strict schemas, and 4,000-token caps. Truncated or
refused output fails. Either lane can report an error while the other still returns.
The fast result does not wait for full scoring. The model panel reports each job,
effort, elapsed time, usage-based estimated cost where available, and replay ID/date.
Cost uses the assumed Spark rates in spec/03, not a billing guarantee.

### Silence boundary in the supplied captures

Timing-only inspection found one genuine **2.48 s pause** in `live-02`; the largest
inter-turn pause in `live-03` is below 1.8 s. A 1.8 s automatic boundary necessarily
ends an answer during that longer pause. The default is unchanged. For longer
thinking pauses, configure a longer silence window or use explicit Done with a
longer window. Done skips the remaining wait; it cannot undo an answer already
completed by silence.

The read-only capture tests configure a **3.0 s** window and verify all 60 full
transcripts with explicit Done, then again with automatic silence completion. Synthetic tests
verify the default boundary, revisions, short pauses, overlapping turns, and Done
draining. These tests do not claim that 1.8 s preserves every long thinking pause.

Proposed decision-log note for review (not applied; specification files unchanged):
record the 2.48 s pause and distinguish full-capture Done/long-window verification
from the default 1.8 s automatic boundary. No classification thresholds or gate
decision are changed by this implementation.

## File fallback

`POST /api/voice/transcribe` accepts a raw audio request body, so browser uploads
need no multipart parsing dependency. The server converts it with ffmpeg to
16 kHz mono 16-bit PCM WAV, validates the ten-minute/32 MB limits, then posts
multipart `request` and `audio` parts to `/v1/asr/transcribe`. Temporary input/output
files are cleaned up. The returned transcript is editable and is not yet scored.
`FFMPEG_BIN` may point to an existing ffmpeg executable if it is not on PATH.

## Private records and no-key replay

Each live ASR session, file transcription, minimal call, and extraction call is
recorded under `VOICE_RECORD_DIR` (default `recordings/voice`, already git-ignored).
JSON includes run ID/date, sanitized request/response, latency, and provider event
arrival times for realtime sessions. WAV bytes are not retained by file fallback;
its source hash identifies the corresponding recorded response. No captures or
recordings belong in a commit.

For offline replay of existing successful records:

```powershell
$env:VOICE_MODE = "replay"
$env:VOICE_RECORD_DIR = "recordings/voice"
$env:DATABASE_PATH = "recordings/voice/events.sqlite3"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Select a recorded realtime run on the practice page. Original arrival timing is
replayed; `VOICE_REPLAY_SPEED=0` skips delays for local diagnostics. Spark responses
are matched by the exact saved request, including the confirmed transcript. File
replay matches the original uploaded bytes and needs neither ffmpeg nor a key.
Unrecorded or edited answers produce an explicit missing-replay error, never a
fabricated model result. Choose a curated record directory when sharing replay mode.

## Verification

Run offline tests with the existing interpreter and no pytest cache provider:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests scripts/probes/test_probes.py scripts/probes/test_spark_latency.py --tb=short
```

Private capture tests read only these original directories and skip if unavailable:

- `C:\Users\chiso\unbluffable\scripts\gate\runs\live-02`
- `C:\Users\chiso\unbluffable\scripts\gate\runs\live-03`

They do not print or copy transcript contents. All other speech fixtures are
invented, and all test model calls use mocks. An installed ffmpeg performs a real
stereo-WAV-to-mono conversion check. An installed Node runs isolated JavaScript
unit checks for acknowledgement order, stale socket handling, echo muting, PCM
resampling, and Done flushing; those checks do not access a real microphone/browser.

Tuesday's public-link exit tests are **not yet verified** by this branch. Local
tests cover a completed wrong posterior producing a challenge and the detector's
90% restated given producing none. A public deploy, real mic/speech playback, and
live end-to-end confirmation remain to be checked; no live model calls were made
during this implementation. Computer Use could not verify the active browser URL,
so the attempted browser smoke test was stopped rather than bypassing that check.
