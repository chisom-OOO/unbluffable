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
- Credits: $150 Meta Model API (claimed; card on Billing). Baseten / Modal / Fireworks applied for, not yet granted. Muse Glimmer and Spark Open are **not** on Meta's API; they need a partner host or own hardware.

## The product (see `spec/01`, `02`, `03`)
- Voice-first interview: the interviewer **speaks** questions and challenges (browser speech; Meta has no TTS), the candidate answers by voice (Muse Voice Transcribe) or text, Muse Spark extracts reasoning with quotes limited to the candidate's own words, exact maths checks every number, and a Bayesian engine picks the next question by expected information gain.
- Signature moments: a live challenge of a committed wrong answer (mid-sentence only if the realtime gate passes; otherwise right after the answer); "same puzzle, new numbers" to separate understanding from memorisation; Spot the bluff on the landing page; a "which model did what" panel each turn.
- Quant pack: three conditional-probability templates with fresh numbers each session (flagship framed as a fraud alert: 1% fraud, 90% detected, 5% false alarms → 2/13 ≈ 15.4%; twin at 2% → 18/67 ≈ 26.9%). The builder may switch the flagship back to the classic medical-test wording (same maths); their call.
- Content rule: own templates only. Lemma (crowd-compiled question bank, unclear provenance) is used only to see what comes up and collect common wrong answers, never copied. No web scraping.
- Open-weights backend + live claim classifier on a partner host for the $10K bonus (go/no-go Fri 30 Oct).

## Decision points
- **Mon 26:** realtime gate (30 recorded clips; pass = ≥8/10 errors caught, 0/20 false challenges, median ≤1.5 s, max ≤3 s). Fail or not passed by 13:00 UK Tue → after-turn challenge.
- **Wed 28:** a carefully prompted Muse Spark chatbot vs Unbluffable on 10 bluffs + 10 real answers. If no advantage, change the headline before building more.
- **Fri 30:** open-weights go/no-go.
- Every deviation goes in `spec/DECISION_LOG.md`; update `STATUS.md` every night.

## Impact plan (largest rubric weight)
Real users: 15–40 candidates, starting with the builder's trading society, plus quant/CS student communities; consent; "fooled it" attempts; 2–3 honest quotes for the video. Name the theme explicitly everywhere.

## Before the repo goes public (Tue 3 Nov)
Remove anything personal or account-related from public files (e.g. the AI-usage note in `STATUS.md`), check `git log -p | Select-String -Pattern "MODEL_API_KEY="` shows no real key, and confirm the repo opens logged out.
