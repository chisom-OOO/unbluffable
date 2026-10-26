# Meta capability sheet

Verified 26 October 2026. Request implementations are in `scripts/probes/`.
This sheet contains measured summaries only. Audio, transcripts, complete model
responses, and raw event captures remain local in ignored directories.

## Live probe results

Earlier attempts were blocked by a missing process key and sent no requests.
The subsequent live runs below succeeded. Times include connection/setup work;
they are not end-of-claim challenge latency.

| Probe | Recorded at (UTC) | Result | Elapsed |
| --- | --- | --- | --- |
| Spark strict extraction | 21:33:02 | HTTP 200; parsed extraction passed local schema checks and verbatim quote matching | 7.237 s |
| Per-turn quote enum | 21:33:10 | HTTP 200; parsed extraction passed the sentence enum and verbatim checks | 10.413 s |
| Wonder short text | 21:34:30 | HTTP 200; nonempty text with a completed finish | 3.337 s |
| Voice file, 7.32 s WAV | 21:36:34 | HTTP 200; JSON response captured; transport success does not establish recognition accuracy | 3.688 s |
| Voice realtime, 7.32 s WAV | 21:36:56 | 14 transcript events, one completed turn, close code 1000 | 9.551 s |
| Voice realtime, 16.234625 s WAV | 21:40:54 | 26 transcript events, one completed turn, close code 1000 | 18.064 s |

Realtime transcript-event counts come from the probe and include terminal transcript
frames; they are not counts of eligible claim partials. Cumulative partials grow
by words and may revise text. See proposed decision-log row 0i and the gate harness
for the number-span stability interpretation. Neither clip decides the 30-clip gate.

Local run IDs, in the same order:

- `66980434e7a34c29ab0316f7a012b94a`
- `325b4e2a855a4b9297ef3882775042e9`
- `0ac8867f4e3d47ed8457c24b27162a4a`
- `4bd55fc8119040b9822f90f831bd7243`
- `b846fa7343dc4864ba08a0f91f3bc8e6`
- `d3c7c6a2390643029d7533d57babc778`

## Probe commands

Run from the repository root. Every Python invocation uses the existing `.venv`.
The key must already be available to the process; scripts access it only with
`os.environ["MODEL_API_KEY"]`. No environment file is opened or environment changed.
Choose fresh capture filenames to preserve prior evidence.

Generate a short synthetic speech fixture, without a microphone:

```powershell
.\scripts\probes\make_sample_wav.ps1
```

Run probes individually, reviewing any specification contradiction before continuing:

```powershell
.\.venv\Scripts\python.exe scripts/probes/probe_spark_strict.py --capture scripts/probes/runs/spark-live-02.json
.\.venv\Scripts\python.exe scripts/probes/probe_quote_enum.py --capture scripts/probes/runs/quote_enum-live-02.json
.\.venv\Scripts\python.exe scripts/probes/probe_wonder.py --capture scripts/probes/runs/wonder-live-02.json
.\.venv\Scripts\python.exe scripts/probes/probe_voice_file.py --wav scripts/probes/sample.wav --capture scripts/probes/runs/voice_file-live-02.json
.\.venv\Scripts\python.exe scripts/probes/probe_voice_realtime.py --wav scripts/probes/sample.wav --capture scripts/probes/runs/voice_realtime-live-03.json
```

Live probes print their parsed results and append detailed attempts to this sheet.
Keep those detailed attempts local or summarize them before committing. Captures
in `scripts/probes/runs/` and the generated `sample.wav` are ignored by git.

Replay without a key, WAV, network connection, or transport dependencies:

```powershell
.\.venv\Scripts\python.exe scripts/probes/probe_spark_strict.py --mode replay --capture scripts/probes/runs/spark-live-01.json --report scripts/probes/runs/spark-replay.md
.\.venv\Scripts\python.exe scripts/probes/probe_voice_realtime.py --mode replay --capture scripts/probes/runs/voice_realtime-live-02.json --report scripts/probes/runs/voice-replay.md
```

Replay is labelled with its original run ID/date and preserves captured arrival
times and outcome. Failed or blocked captures do not become passing evidence.

## Implementation constraints

Spark uses the extraction schema from spec/03, `strict: true`, explicit low reasoning
effort, and a 4,000-token cap. All object properties are required and additional
properties are forbidden. Only a completed `stop` finish is accepted; truncated
output fails. Quotes and the committed answer must be found verbatim in the source.
The sentence-enum probe constrains quotes to the actual synthetic answer sentences.

Live HTTP/WebSocket transports use installed `httpx` and `websockets`. No packages
are installed. WAVs must be mono 16-bit PCM at 16 or 24 kHz, at most ten minutes and
32 MB. File transcription uses multipart `request` and `audio` parts. Realtime
uses an authorization frame, paced raw PCM, and final draining after `endStream`.
Credentials are excluded from captures and sanitized if echoed by the provider.

Realtime arrival times use UTC and a monotonic clock. They are not word timestamps,
confidence scores, or hand-labelled claim times. The [gate harness](../scripts/gate/README.md)
uses hand-labelled claim ends to compute challenge latency and report the gate criteria.

## Verification and Monday exit tests

The combined offline suite passed: **76 passed**, with one existing scaffold
FastAPI/Starlette deprecation warning. No live gate calls were made by that suite.

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests scripts/probes/test_probes.py scripts/gate/test_gate.py
```

| Monday exit test | Status |
| --- | --- |
| Strict Spark call returns quotes found in the text | Pass: live run `66980434e7a34c29ab0316f7a012b94a` |
| Realtime gate decided and logged | Pending the full labelled 30-clip live run |
| Pinned engine tests from spec/02 section 6 pass | Not met: pinned engine tests are absent |

No product decisions were changed. Decision-log row 0i is a proposed clarification
applied to the gate harness under the builder's explicit instruction.

## Official API references checked

- [Structured output](https://dev.meta.ai/docs/structured-output)
- [Reasoning](https://dev.meta.ai/docs/reasoning)
- [File transcription](https://dev.meta.ai/docs/api-reference/voice/transcribe)
- [Realtime transcription](https://dev.meta.ai/docs/api-reference/voice/realtime)
- [Speech to text](https://dev.meta.ai/docs/speech-to-text)
