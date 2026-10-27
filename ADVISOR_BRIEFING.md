# Advisor briefing

For any new Claude chat or account helping with Unbluffable. Read this first, then `STATUS.md` (where things stand) and `spec/DECISION_LOG.md` (what changed and why). The full specification is in `spec/`; coding agents follow `CLAUDE.md` / `AGENTS.md`.

## The builder
- Solo builder, Indie track. Prepares for quant interviews firsthand and has competed in probability competitions (theme: **Build for Your World**).
- Works on Windows; repo at `C:\Users\chiso\unbluffable`; Python 3.12 in a `.venv` per worktree; can work up to ~10 h/day.
- Tools: Codex (bulk of the build), Claude Code (engine, extraction, reviews), Muse Code (small pieces, Contributor mode, never sees `.env` or tester data). Do not point Claude Code or Codex at Meta's API: it spends the $150 credits.
- How to advise: be direct and honest (including about odds), give exact commands for Windows PowerShell (one command per line; no `&&` or `grep`), and don't change the plan without build evidence.
- Framing: Unbluffable is **a voice interview platform for many high-stakes interviews** (quant, software, engineering, medical-school, PhD, Oxbridge). Quant/probability is the first deep pack built for the hackathon, not the whole product. Don't describe it as "just quant".
- Avoid over-caution on wording: a probability puzzle is not medical advice; interview prep is not an "AI for Education chatbot". Position clearly, don't hedge.

## The event (confirmed at kickoff, 26 Oct)
- Meta Global AI Developer Hackathon. Submissions due **4 Nov, 9 PM ET = 02:00 UK Thu 5 Nov**. Judging 5–8 Nov. Finals **9 Nov, 12 PM ET = 17:00 UK**. Community-vote winner 16 Nov.
- Rules: new work only (pre-event planning docs in `spec/` are disclosed as prior work; no code before kickoff); **public GitHub repo** (check it opens logged out); **3-minute demo video**; demo only what was built; nothing using code, data or assets without rights; avoid the anti-project list (medical advice, basic RAG, "AI for Education" chatbots, job-application screeners, etc.).
- Judging: stage 1 pass/fail (theme fit + uses Meta AI products); stage 2 scored 0–10 per criterion; finals = judges watch the 3-minute video and rank the top 5 per track.
- **Rubric:** Impact 30% · Use of Meta AI tooling 25% (creative, beyond basic integration) · Technical depth 20% · Demo 25%.
- Indie prizes: 1st $150K, 2nd $100K, 3rd $75K, 4th $50K, 5th $25K. Bonus: Most Viral on X $20K; Best Build on Meta Open Weights (Muse Glimmer / Spark Open) $10K; Community Vote $10K; Best Agentic $5K; Best Creative (Muse Image/Wonder) $5K.
- Credits: $150 Meta Model API (claimed; card on Billing). **Baseten $100 granted (27 Oct):** Muse Spark Open at `https://inference.baseten.co/v1`, model exactly `meta-models/muse-spark-open-1026` (always reasons), key in `.env` as `BASETEN_API_KEY`. Modal / Fireworks applied for, not granted. Muse Glimmer and Spark Open are **not** on Meta's API.

## The product (see `spec/01`, `02`, `03`)
- Voice-first interview: the interviewer **speaks** questions and challenges (browser speech; Meta has no TTS), the candidate answers by voice (Muse Voice Transcribe) or text, Muse Spark extracts reasoning with quotes limited to the candidate's own words, exact maths checks every number, and a Bayesian engine picks the next question by expected information gain.
- Signature moments: a live challenge of a committed wrong answer (mid-sentence only if the realtime gate passes; otherwise right after the answer); "same puzzle, new numbers" to separate understanding from memorisation; Spot the bluff on the landing page; a "which model did what" panel each turn.
- Quant pack: three conditional-probability templates with fresh numbers each session (flagship framed as a fraud alert: 1% fraud, 90% detected, 5% false alarms → 2/13 ≈ 15.4%; twin at 2% → 18/67 ≈ 26.9%). The builder may switch the flagship back to the classic medical-test wording (same maths); their call.
- Interviewer behaviour (decision log 3, 3a, 3b): Socratic nudge rounds (≤4) after wrong answers; hints on request or when stuck, written by Spark for the candidate's own reasoning (no fixed count) with a no-new-numbers leak guard; each question scored on its final outcome discounted by help (w = 2/(2+H), +1 step if the challenge was needed; not recovered = the wrong answer); time vs guide on the end card; escalation to two harder follow-ups for strong candidates (`02` §7).
- Content rule: own templates only. Lemma (crowd-compiled question bank, unclear provenance) is used only to see what comes up and collect common wrong answers, never copied. No web scraping.
- Open-weights backend + live claim classifier on a partner host for the $10K bonus (go/no-go Fri 30 Oct).

## Decision points
- **Mon 26 (done):** realtime gate failed: 2/10 errors caught (0/20 false). One held-out retry with widened rules: 8/10 on the old clips but **1/10 on 30 new clips** (decision log 1, 1a, 1b). **After-turn challenge is final.** Do not reopen mid-sentence interruption unless a fast open-weights classifier is available (needs sponsor GPU credits, not granted) and a fresh held-out gate passes.
- **Wed 28:** a carefully prompted Muse Spark chatbot vs Unbluffable on 10 bluffs + 10 real answers. If no advantage, change the headline before building more.
- **Fri 30:** open-weights go/no-go.
- Every deviation goes in `spec/DECISION_LOG.md`; update `STATUS.md` every night.

## Where things stand (Tue 27 Oct, 13:50 UK) — read this first
**Live on Render** from `main` (Docker, auto-deploys on push; free instance for now, switch to always-on paid before judging 4–9 Nov). Keep the link private until per-session limits exist (Fri).

**Blocking right now — Render Spark calls fail.** On the Render link `/practice`, transcription and the spoken "Okay, let me check your working" work, but every Muse Spark call returns "The model request failed". Locally the same flow works (wrong answer challenged; restated given not). Fixes pushed so far: keys are now `.strip()`ped (a pasted trailing newline breaks HTTP headers; realtime still worked because the key goes in a JSON frame) — `3c54a09`; server-side logging of the failure reason (HTTP status + Meta error type/code/message, never transcript or key) — `ed0d2b0`. **Next step:** after the latest deploy is Live, reproduce once, then read Render Logs for the line `model call /chat/completions failed: ...` and fix from that.

**Branches waiting to be reviewed and merged into `main`:**
- `ui` (Claude Code, folder `unbluffable-engine`): Exam Room design (Newsreader serif = interviewer, IBM Plex Sans = candidate, Plex Mono = numbers; teal accent, amber challenges; light + dark). Screens with fake data at `/ui`, `/ui/interview`, `/ui/end`. **Fixes requested, not yet confirmed done:** (1) remove the fake "Recorded on 2026-10-21" label (label it a sample); (2) challenge/nudge text must be a Socratic question, never an explanation; (3) hands-free per decision log 4 — no "Tap to talk", Done only a small fallback; (4) end-card copy per 3b: "Scored on where you end up, discounted by the help it took"; (5) add `data/` to `.gitignore`. **Pending builder decision:** drop "Out of 2,000" from the puzzle text (percentages only; hints may introduce a round population) — recommended yes.
- `turn-taking` (Codex, folder `unbluffable-voice`): hands-free Start, content-aware end-of-answer detection (cues, then Spark `minimal`), ~8 s silence prompt, headphones-only barge-in, recorded replay. Acceptance criterion: no completion before a commitment/question/closer or mid-thought (a completion right after an explicit closer is correct). Replay: 0 early completions; **live acceptance run in progress** (`python -m voice.acceptance --mode live --capture-root "C:\Users\chiso\unbluffable\scripts\gate\runs" --records "$env:TEMP\unbluffable-turn-taking"`).

**Already in `main`:** skeleton + CI; engine (pinned tests, spoken numbers); `llm/` strict extraction with record/replay (git-ignored default dir) and backends `meta_api` + `open_weights` (Baseten Muse Spark Open, schema in prompt + one repair); voice after-turn path (`/practice` test page); probes; gate harness; spec rows 3, 3a, **3b** (scored on final outcome discounted by help: w = 2/(2+H), +1 step when the challenge was needed; not recovered = the wrong answer) and 4 (hands-free turn-taking).

**Live facts:** full extraction 7–10 s; minimal schema + `minimal` effort median 0.90 s (max 2.75 s); `low` median 2.49 s. Realtime partials word by word ~0.3–0.5 s apart; the service ends a turn at every short pause. Baseten vs Meta comparison (`scripts/probes/probe_spark_latency.py --mode live --effort all`) not yet run.

**Decided:** after-turn challenge is final (keyword live interruption failed held-out, 1/10; a model-judged live classifier is only a Friday stretch with a fresh held-out gate). **CV upload: not in the hackathon build** (can't be checked by exact maths, personal data, job-screener perception, 1–2 days) — roadmap slide only; at most a Friday "paste CV to choose pack/difficulty" with no CV questions.

**Today's remaining plan (Tue):** fix Render Spark calls → public-link exit test (wrong answer challenged; "the detector catches 90% of fraud" not) on laptop and phone → merge `turn-taking` and `ui` after review → Baseten comparison → update STATUS daily log. Wed: interview flow wiring (multi-question, twins, nudges/hints for T1 per `02` §7), early careful-chatbot check, consolidate voice/ to use `llm/` and `engine.answers` (one Spark client, one number parser).

**Folders and keys:** `C:\Users\chiso\unbluffable` (main), `unbluffable-engine` (Claude Code, branch `ui`), `unbluffable-voice` (Codex, branch `turn-taking`). `.env` in each holds `MODEL_API_KEY` and `BASETEN_API_KEY`; load per PowerShell window with `$env:NAME = ((Get-Content .env | Select-String '^NAME=').Line -split '=', 2)[1]`. **Never use `Set-Content` on `.env`.** Render holds the keys as environment variables.

**Test data:** 60 builder-recorded flagship clips (`recordings/gate/`, `recordings/gate2/`; git-ignored; never paste into coding sessions).

**Process:** one chat edits `spec/` at a time; agents push branches; the advisor reviews and merges into `main`.

## Impact plan (largest rubric weight)
Real users: 15–40 candidates, starting with the builder's trading society, plus quant/CS student communities; consent; "fooled it" attempts; 2–3 honest quotes for the video. Name the theme explicitly everywhere.

## Before the repo goes public (Tue 3 Nov)
Remove anything personal or account-related from public files (e.g. the AI-usage note in `STATUS.md`), check `git log -p | Select-String -Pattern "MODEL_API_KEY="` shows no real key, and confirm the repo opens logged out.
