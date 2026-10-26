# 03 — Architecture and Meta API

## Stack
Python 3.12 · FastAPI (with WebSocket support) · Jinja2 + HTMX + a small amount of plain JavaScript (mic capture, audio playback, live transcript) · SQLite (one JSON event log per session) · pydantic · `openai` SDK pointed at Meta · `fractions` for exact maths · pytest · Docker (with ffmpeg) → Render (fallback Fly, then local + tunnel).

## Repo layout
```
engine/      exact maths, templates, generator, likelihoods, selection, labels (pure; tests run offline)
content/     likelihoods.yaml (versioned), templates.yaml, practice tips, demo seeds
llm/         Meta client, extraction prompt + schema, validator, record/replay
voice/       realtime relay, file transcription, number normalisation, claim rules
app/         routes, templates, static JS
eval/        hard set, tricky utterances, results, analysis (McNemar)
replay/      recorded real runs for the demo and the no-key mode
docs/        capability sheet (probe results), DECISION_LOG.md, daily notes
tests/       pinned engine tests, gate tests, injection tests
```

## Meta Model API — facts verified on dev.meta.ai, 25 Oct 2026 (re-check at kickoff)
- Base URL `https://api.meta.ai/v1`; key in env `MODEL_API_KEY` (pass it explicitly to the `openai` client); OpenAI-SDK compatible.
- Models: `muse-spark-1.3` (Standard), `muse-wonder-1.0`, `muse-voice-transcribe-1.0`, `muse-image-1.0`, `sam-3.1`. Muse Spark Open and Muse Glimmer are **not** on the Model API.
- **Never** use `-contributor` IDs for real answers (Contributor mode content may train Meta models). Assert the Standard ID at startup.
- Structured output (Chat Completions): `response_format = {"type": "json_schema", "json_schema": {"name": ..., "strict": true, "schema": ...}}`. Strict subset: no `oneOf`/`allOf`; `anyOf` only below the root; every object `additionalProperties: false`; every key in `required`. Set `strict: true` explicitly (default false hides schema bugs). Nullable handling undocumented → use sentinel strings like `"none"`.
- Reasoning: set `reasoning_effort` explicitly (use `"low"` for extraction; `"none"` is rejected for Spark). Reasoning tokens bill at the output rate and count toward the token cap → set the cap ≥ 4,000 and treat a truncated finish as a failure.
- Spark 1.3 audio input is "not fully supported" → never send audio to Spark; use Voice Transcribe.
- Pricing (Spark Standard): $1.25 / M input, $4.25 / M output; rate limit 3,000 RPM per team.
- Voice Transcribe, file: `POST /v1/asr/transcribe`, multipart, WAV mono 16-bit PCM at 16 or 24 kHz, ≤ 10 min, ≤ 32 MB, key in the `Authorization` header.
- Voice Transcribe, realtime: `wss://api.meta.ai/v1/asr/realtime`; authenticate in the **first JSON frame** (`authorization.accessToken = "Bearer <key>"`) within 10 s; the HTTP header is ignored; no key in query strings. `ENDPOINTING` mode emits `speechStart`, `transcript`, `speechEnd`, `speechComplete`. Partials are cumulative and **a new partial can revise or remove earlier text**. **No word-level timestamps or confidence scores.** `keywords` (set in the handshake) bias recognition.

## Extraction schema (Muse Spark, strict)
Flat object, all keys required:
- `committed_answer_text`: string — verbatim span of the final claimed answer, or `"none"`.
- `reasoning_quotes`: array of objects `{quote: string (verbatim), step: enum[base_rate, likelihood, false_positive_count, total_positive, posterior, restated_given, hypothetical, self_correction, other]}`.
- `reasoning_code`: enum[valid, misconception, other_wrong, vague].
- `misconception_name`: enum[transposed_conditional, base_rate_neglect, ignores_prior, ignores_data, none].
- `self_corrected`: boolean.
Code (not the model) locates every quote in the transcript, normalises numbers, runs the exact check, and decides the outcome (`02` §2). Quotes not found verbatim are dropped. Probe on Monday: a per-turn schema whose `quote` field is an enum of the answer's sentences (constrained decoding makes quotes real by construction); fall back to code-side matching if it fails.

## Voice path
- **Realtime (if the gate passes):** browser mic → app WebSocket → server relay → Meta realtime (key added server-side) → partials back to the browser. Mute the mic stream while the browser's built-in voice speaks a challenge (Meta has no text-to-speech; disclose the browser voice). Headphones recommended.
- **File fallback (always available):** browser records (webm/opus) → server converts with ffmpeg to 16 kHz mono WAV → `POST /v1/asr/transcribe` → editable transcript → user confirms → scored.
- **Number normalisation:** at least: "two over thirteen", "two thirteenths", "fifteen point four percent", "about fifteen percent", "nought point one five", "0.15", "15%". Use `keywords` for terms like "sensitivity", "prevalence", "false positive".

## Fast lane (no model) and claim rules
Runs on every partial. Fires a challenge only when ALL hold:
1. A number follows a **claim marker** ("so the probability is", "so it's", "the answer is", "you're about … likely").
2. The same claim appears in **2 consecutive partials** and persists **≥ 500 ms**.
3. It is not a restated given ("the test has 90% sensitivity"), a hypothetical ("if it were…"), or after "maybe"/"no"/"wait".
4. The exact check says the number is wrong, or it matches a named wrong value.
The slow lane (Spark extraction) runs after each pause/turn end.

## Monday realtime gate (measurable)
Test set: 30 clips you record — 10 committed wrong posteriors, 10 non-errors (restated sensitivity, hypotheticals, self-corrections), 10 correct answers. Mark each clip's end-of-claim time by hand.
Pass (all): ≥ 8/10 committed errors challenged; **0/20** false challenges; latency from end of claim median ≤ 1.5 s and max ≤ 3 s.
Fail any criterion, or not passed by **13:00 UK Tuesday** → after-turn challenge on `speechEnd`/`speechComplete` (or file fallback). Log the decision. Spend no more time on mid-sentence interruption.

## Ops and safety
- Always-on instance (no cold starts). Per-session limits (not per-IP; judges may share networks). Reserved daily budget for 4–9 Nov. Cap trip → banner + no-model fallback.
- Record/replay every live call during development; replay mode labelled with run ID and date.
- Logs: no raw answers or keys in routine logs. Consent text before testers submit audio.
- Tag the build at submission; hotfix only during judging.
