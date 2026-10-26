# Status

Living checklist. Update it at the end of every day. Any new chat or agent should read this first, then `spec/00_START_HERE.md`.

**Last updated:** Mon 26 Oct, 12:20 UK (pre-kickoff)
**Phase:** setup; spec frozen (v12); no code yet
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
- [ ] API key saved to `.env` in the repo folder (`Set-Content -Path .env -Value "MODEL_API_KEY=..."`)
- [x] Render account (signed in with GitHub); no service yet. First deploy Tue as a **Web Service**; plan persistence for tester data (see `spec/03`, Ops). Switch to an always-on paid instance for judging (4–9 Nov)
- [ ] Mic and headphones tested
- [ ] Two-sentence firsthand story written
- [ ] Gate-clip script written (10 wrong posteriors; 10 restated givens, hypotheticals and self-corrections; 10 correct answers)
- [ ] 3 flagship puzzles chosen, with their classic wrong answers

## At kickoff
- [ ] Watch the livestream; read the details page (problem statements, judging, submission requirements, rules)
- [ ] Read the Official Rules: UK-student eligibility, pre-existing work (disclose `spec/` if required), AI-assistance disclosure, video length, IP and usage rights, team changes, portal time zone
- [ ] If anything conflicts with the spec, log it in `spec/DECISION_LOG.md` before building
- [ ] From ~17:00: skeleton on `main`, then worktrees (`engine` for Claude Code, `voice` for Codex), copy `.env` into each

## Open decisions
- **Sponsor bonus prizes (unverified):** if prizes reward creative use of Baseten, Modal or Fireworks, the proposed integration is a fast open-weights "is this a committed claim?" classifier (Muse Glimmer on Baseten) for the live interruption, a Fireworks open-weights comparison row in the results, and Modal sandboxes for the software pack if built. Not in the spec yet; decide once the prize rules are known, then log it.
- **AI usage:** main Claude Pro account ~26% left this week; a second Claude Pro account (your own) for one week, to start around Wed 28 Oct. Codex takes the bulk of the build; Claude takes the engine, extraction and reviews; Muse Code (Contributor mode, never sees `.env` or tester data) takes small pieces such as the number normaliser. Claude Code and Codex are not pointed at Meta's API by default (it would spend the $150 credits).

## Daily log
| Date | Works | Failed | Decisions | Next |
| --- | --- | --- | --- | --- |
| Mon 26 | | | | |
