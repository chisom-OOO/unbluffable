# 07 — Prompts for Meta's AI (Muse Code or Meta AI)

Paste the **session opener** first, attach the listed files, then the task prompt. One task per session. Ask for tests first.

## Session opener (every session)
> You are helping me build "Unbluffable" for the Meta Global AI Developer Hackathon. The attached files are a frozen, authoritative specification. Follow them exactly. Do not invent API behaviour: when a Meta Model API detail matters, tell me which docs page to check, and treat the facts in 03 as verified on 25 Oct but re-checkable. Do not change product decisions; if build evidence suggests a change, stop and propose an entry for DECISION_LOG.md instead. Write tests first, keep the engine pure and offline-testable, keep API keys server-side, never use "-contributor" model IDs. At the end, list exactly which exit tests now pass and which fail.

## Mon — skeleton and probes (attach 00, 03, 04)
> Create the repo layout in 03 with a FastAPI app, SQLite event log, and a minimal page. Then write probe scripts that: (1) call muse-spark-1.3 with a strict json_schema and print the parsed result; (2) try a per-turn schema where a quote field is an enum of the answer's sentences; (3) call muse-wonder-1.0 with a short text prompt; (4) send a WAV to /v1/asr/transcribe; (5) open the realtime WebSocket, authenticate in the first frame, stream a WAV, and print every partial with arrival times. Save results to docs/capability_sheet.md.

## Mon — realtime gate (attach 03)
> Build a gate harness: it streams each of my 30 recorded clips through the realtime relay, applies the claim rules in 03 (claim marker, 2 consecutive identical partials, ≥500 ms persistence, exclusions for restated givens, hypotheticals, self-corrections), and outputs, per clip, whether a challenge fired and the latency from the hand-marked end-of-claim time I provide in a CSV. Report pass/fail against the criteria in 03.

## Mon/Tue — engine (attach 02)
> Implement engine/ exactly per 02: exact-fraction templates T1–T3, the generator with whole-number natural frequencies and the collision filters (including twins and the "Recited" value), the likelihood tables loaded from content/likelihoods.yaml, the posterior update with the twin conditioned on the first outcome, expected-information-gain-per-minute selection, labels and stopping. First write the pinned tests in 02 §6 and the selection table in §4; they must pass with tolerance ±0.002.

## Tue — voice and fast lane (attach 01, 03)
> Implement the voice path in 03 (realtime relay with mic muting during browser speech if the gate passed; otherwise after-turn on speechEnd; the file-upload fallback always), the number normaliser with the listed phrasings, and the fast-lane claim rules. Add tests: "the detector catches 90% of fraud" must not trigger; "so if a transaction gets flagged it's about 90 percent likely to be fraud" must trigger for the flagship.

## Tue/Wed — extraction (attach 02, 03)
> Implement llm/ extraction with the strict schema in 03, reasoning_effort "low", token cap ≥4000, truncated finishes treated as failures, verbatim-quote location in code, and outcome coding per 02 §2 (a wrong number can never be Correct). Add record/replay of every call. Add prompt-injection tests (answers containing instructions must be quoted and ignored).

## Wed — interview flow + early check (attach 01, 02, 05)
> Wire the interview screen per 01: puzzle, voice/text answer, editable transcript, challenge, engine-selected next question, labels, end card. Then write eval/early_check.py that runs 10 bluffs and 10 real answers through the careful-chatbot arm and Unbluffable and prints a paired table.

## Thu — landing and Spot the bluff (attach 01)
> Build the hook-first landing (mic ready; labelled replay after 3 s) and the Spot the bluff card per 01, with randomised bluffer, one-✗ first reveal and "show the working".

## Fri — hardening (attach 03)
> Add hostile-input handling (silence, garbled audio, echo, injection, off-bank questions), per-session limits, a reserved judging budget, the cap-trip banner and the no-model fallback (exact checks + new numbers, typed numbers only). Verify everything works with the API key removed in replay mode, on a phone, and in Safari.

## Sat — evaluation (attach 05)
> Freeze and hash the extraction prompt. Implement eval/ to run the paired three-arm comparison with exact McNemar tests, the interruption test (60 non-errors, 40 errors) with one-sided upper bounds, and the red-team run. Save results as JSON and a markdown table. Never round in our favour; report counts.

## Sun–Tue — README, video, submission (attach 06)
> Draft the README first screen and the submission description per 06, filling only measured numbers from eval/results. List every claim in the description and the file that supports it.
