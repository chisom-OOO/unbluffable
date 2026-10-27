# Status

Living checklist. Update it at the end of every day. Any new chat or agent should read `ADVISOR_BRIEFING.md` and this file first, then `spec/00_START_HERE.md`.

**Last updated:** Tue 27 Oct, 13:20 UK
**Phase:** day 2: deployed on Render; turn-taking (Codex) and UI (Claude Code) in progress
**Next decision points:** Mon realtime gate (`spec/03`); Wed careful-chatbot check (`spec/05`)

## Done
- [x] Spec frozen (v12) and pushed to `spec/`, with `CLAUDE.md` and `AGENTS.md` for coding agents
- [x] Private repo `chisom-OOO/unbluffable` created and cloned to `C:\Users\chiso\unbluffable`
- [x] `.gitignore` keeps `.env`, `recordings/`, `eval/raw/` out of git; `.env.example` added
- [x] Optional extras added to the spec: per-turn model panel; reasoning-effort comparison

## Before kickoff (16:00 UK)
- [x] `git pull` in the local repo
- [x] dev.meta.ai account; claim the $150 credits via the organiser's form (deadline Wed 4 Nov, 9 PM ET); add a card on Billing; set the $150 spend notification
- [ ] Join the Discord (announcements, office hours, workshops). Building solo, no teammate
- [x] Install Python 3.12, ffmpeg, Docker Desktop; check `claude` and `codex` start
- [x] Muse Code installed and logged in (Contributor mode for coding only)
- [x] API key saved to `.env` in the repo folder (`Set-Content -Path .env -Value "MODEL_API_KEY=..."`)
- [x] Render account (signed in with GitHub); no service yet. First deploy Tue as a **Web Service**; plan persistence for tester data (see `spec/03`, Ops). Switch to an always-on paid instance for judging (4–9 Nov)
- [ ] Mic and headphones tested
- [ ] Two-sentence firsthand story written
- [x] Gate-clip script written (10 wrong posteriors; 10 restated givens, hypotheticals and self-corrections; 10 correct answers)
- [ ] 3 flagship puzzles confirmed (fraud alert, two machines, two coins in `spec/02`), or swapped after skimming Lemma for the most common types; classic wrong answers listed

## At kickoff
- [x] Watch the livestream (rubric, rules, bonus prizes captured in `spec/06` and the decision log)
- [ ] Read the event details page for anything not in the kickoff (eligibility, IP/usage terms); apply for Baseten, Modal and Fireworks credits in #resources now (limited places)
- [ ] If anything conflicts with the spec, log it in `spec/DECISION_LOG.md` before building
- [x] From ~17:00: skeleton on `main`, then worktrees (`engine` for Claude Code, `voice` for Codex), copy `.env` into each (`voice` worktree still to create, Tue)

## Open decisions
- **Sponsor/bonus prizes (resolved at kickoff):** $10K Best Build on Meta Open Weights → open-weights backend + claim classifier on a partner host (go/no-go Fri). $20K Most Viral (X) and $10K Community Vote → after submission. See decision log 0e–0g.
- **AI usage:** main Claude Pro account ~26% left this week; a second Claude Pro account (your own) for one week, to start around Wed 28 Oct. Codex takes the bulk of the build; Claude takes the engine, extraction and reviews; Muse Code (Contributor mode, never sees `.env` or tester data) takes small pieces such as the number normaliser. Claude Code and Codex are not pointed at Meta's API by default (it would spend the $150 credits).

## Daily log
| Date | Works | Failed | Decisions | Next |
| --- | --- | --- | --- | --- |
| Mon 26 | Skeleton + CI; engine merged (pinned §6 and §4 pass); probes live: strict Spark with verbatim quotes, Wonder, voice file, realtime partials (~0.1 s behind audio, no revisions); gate harness; 273 tests pass | Realtime gate: 2/10 errors caught (0/20 false, median 1.09 s) | After-turn challenge final (log 1, 1a, 1b: held-out retry 1/10); clarifications 0i (engine), 0j (partial stability) | Tue: voice path (after-turn on speechEnd + file fallback), number normaliser, extraction prompt (define "hypothetical" step), deploy to Render; workshop 16:00 |
