# Unbluffable — build pack (frozen v12)

This folder is the **authoritative specification** for the Unbluffable entry to the Meta Global AI Developer Hackathon (Indie track). It was written before kickoff as a plan only; it contains no code. All code is written after kickoff (Mon 26 Oct, 17:00 UK).

> **Sounding right isn't the same as being right.**
> A spoken interview practice tool that challenges your reasoning the moment it goes wrong, checks numbers exactly, and asks the same puzzle with new numbers to separate understanding from memorisation.

## Files, in reading order

| File | Use it for |
| --- | --- |
| `00_START_HERE.md` | Rules of the build, kickoff checklist, how to brief Meta's AI |
| `01_PRODUCT_SPEC.md` | What the user sees: screens, flows, labels, copy |
| `02_ENGINE_SPEC.md` | The maths: puzzle templates, likelihood tables, selection, labels, pinned tests |
| `03_ARCHITECTURE_AND_API.md` | Stack, repo layout, Meta API facts, schemas, voice path, the Monday gate, fallbacks |
| `04_BUILD_PLAN.md` | Day-by-day tasks, exit tests, cut order |
| `05_EVIDENCE_PLAN.md` | What is measured, how, and the statistics |
| `06_DEMO_AND_SUBMISSION.md` | Video script, description, README, finals, Q&A |
| `07_PROMPTS_FOR_META_AI.md` | Copy-paste prompts for each build session |
| `DECISION_LOG.md` | Template; every deviation from this spec is logged here |

## Rules of the build (non-negotiable)

1. **This pack is the source of truth.** If an AI assistant suggests something that contradicts it, the pack wins unless build evidence says otherwise.
2. **Change only on evidence.** A failed gate, a failed exit test, or a measured result. Record every change in `DECISION_LOG.md` (date, evidence, decision, impact).
3. **Exit tests are hard.** If a day's exit test fails, take the next item in the cut order (`04_BUILD_PLAN.md`) before adding anything.
4. **Two checkpoints decide the shape of the entry:** the **Monday realtime gate** (`03`) and the **Wednesday careful-chatbot check** (`05`).
5. **Never claim more than you measured.** No "can't be fooled", "calibrated", "first", or "proves understanding". Probabilities are model estimates under stated assumptions.
6. **Security:** API keys only on the server. Never use `-contributor` model IDs for real user answers.

## Key times (UK)
- Kickoff: Mon 26 Oct (be ready 16:00; first project code 17:00).
- Submit: by 23:00 Tue 3 Nov if the portal allows later edits, else by 17:00 Wed 4 Nov.
- Hard deadline: 02:00 Thu 5 Nov (= 9 PM ET 4 Nov). Confirm the portal's time zone.
- Judging 4–8 Nov (keep the link alive and budgeted). Live finals 9 Nov.

## Kickoff checklist (Mon 26 Oct, before 17:00)
- [ ] Read and save the Official Rules: eligibility (UK student), pre-existing work (disclose this plan pack if required), AI-assistance disclosure, video length, IP/usage rights, team changes, portal time zone.
- [ ] Credits: Meta Model API credits; partner credits (Baseten, Modal, Fireworks) if offered. Join the Discord.
- [x] Building solo (decided 26 Oct).
- [ ] Re-check Meta docs: quickstart, models, structured output, speech-to-text, pricing (facts in `03` were verified 25 Oct).
- [ ] Accounts ready: GitHub repo (empty), hosting with WebSocket support (Render or Fly).
- [ ] Headphones + mic tested (prevents the interviewer's voice feeding back into the mic).
- [ ] Your two-sentence firsthand story written.

## How to brief Meta's AI
Open a session, attach or paste `00`–`03` (and the file for the day's task), then use the matching prompt from `07_PROMPTS_FOR_META_AI.md`. Keep each session small: one day's task, its exit test, and the relevant spec files. End each day by updating `DECISION_LOG.md` and a short daily note (what works, what failed, next task).
