# 04 — Build plan (≈66 h committed, ≈14 h buffer)

Work up to 10 h on a stretch day, but don't stack 10-hour days. If a day's exit test fails, take the next cut before adding anything. Update `DECISION_LOG.md` and a daily note every night.

| Day | Tasks | Exit test |
| --- | --- | --- |
| **Mon 26** (17:00–~01:00, ~8 h) | Rules, credits, teammate post. Skeleton (FastAPI, SQLite, page). Probes: Spark strict schema, quote enum, Wonder, Voice file + realtime → `docs/capability_sheet.md`. **Realtime gate:** record 30 clips, run criteria. Exact checker + generator for T1–T3. | Gate decided (logged). Strict Spark call returns quotes found in the text. Engine tests for §6 pass. |
| **Tue 27** (~9 h) | Voice path per gate (realtime relay + echo muting, or after-turn on speech end; file fallback always). Fast lane: normalisation + claim rules. Engine: likelihood tables, selection, labels, stopping. Replay mode. Always-on deploy. | A spoken wrong posterior is challenged on the public link; "the test has 90% sensitivity" is not. |
| **Wed 28** (~8 h) | Quant pack complete: 3 templates, twins, labels, end card + practice tips. **Early careful-chatbot check** (`05`). | Full interview by voice and text. Headline confirmed or changed (logged). |
| **Thu 29** (~8 h) | Hook-first landing with replay. Spot the bluff (record both candidates; randomise). Draft hard set + 60 tricky non-error utterances. Consent text; invite attackers. | Landing + Spot the bluff work on a phone. |
| **Fri 30** (~8 h) | Hostile inputs (bad audio, echo, injection, off-bank). Spend caps, judging budget, no-model fallback. Safari test. **Open-weights backend + claim classifier on a partner host; go/no-go** (`03`). | Stable on phone and Safari; fallback works with the key removed. |
| **Sat 31** (~8 h) | Freeze + hash the extraction prompt. Paired hard set (3 arms). Interruption tests (60 non-errors, 40 errors). Red team (Wonder). | Result files in `eval/results/`. |
| **Sun 1 Nov** (~6 h) | Rescore attacker attempts with the frozen prompt; hand-label "fooled". README first screen + roadmap slide. Clean-clone test. Polish the first 20 s. | Clean clone runs the demo. |
| **Mon 2** (~7 h) | **Feature freeze.** Final script. Record footage (incl. a spoken answer). Voice-over with placeholder numbers. Rough edit. | Rough cut exists. |
| **Tue 3** (~6 h) | Swap in final numbers; finish the **3:00 video**. Submission text + disclosures (prior work = `spec/` planning docs). Make the repo **public**; check it opens logged out. Portal fill; flag bonus prizes. Submit and tag. Cut a 30–45 s clip for X. | Receipt saved. |
| **Wed 4** | Hotfix only. Finals kit (90 s and 3 min versions, second device, hotspot). | Live link checked. |

## Cut order (take the next one when a day slips)
1. Optional extras (model panel, effort comparison, Monte Carlo cross-check, software pack).
2. Spot the bluff (the landing replay stays).
3. Third template (ship T1 + T2).
4. Mid-sentence interruption → after-turn challenge.

**Never cut:** the always-on link, replay mode, exact checks, voice in the interview, the evidence line, the 3:00 video, the public repo, the submission.

## Daily note template
```
Date / version:
Works:
Failed (exact test):
Decision(s) logged:
Next smallest task:
Risks:
```
