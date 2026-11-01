# Unbluffable — instructions for coding agents

> `CLAUDE.md` (Claude Code) and `AGENTS.md` (Codex, Muse Code) must stay identical. Edit both together.

This repo builds **Unbluffable** for the Meta Global AI Developer Hackathon (Indie track). The authoritative specification is in `spec/` (frozen v12). Read `spec/00_START_HERE.md`, then `spec/DECISION_LOG.md` for every change since the plan, then the files your task needs:
- `spec/01_PRODUCT_SPEC.md`: screens, flows, labels, copy rules
- `spec/02_ENGINE_SPEC.md`: templates, likelihood tables, selection, labels, pinned tests
- `spec/03_ARCHITECTURE_AND_API.md`: stack, repo layout, Meta API facts, schema, voice path, realtime gate
- `spec/04_BUILD_PLAN.md`: day tasks, exit tests, cut order
- `spec/05_EVIDENCE_PLAN.md`: evaluation and statistics

## Rules
1. **The spec wins.** Do not change product decisions, likelihood values, thresholds, labels or claims. If build evidence suggests a change, stop and propose an entry for `spec/DECISION_LOG.md` instead of making it.
2. **Tests first.** For engine work, write the pinned tests in `02 §6` and the selection table in `02 §4` before implementing; tolerance ±0.002. Keep `engine/` pure (no network, no model calls) and runnable offline.
3. **Stay in your lane.** Only edit the directories named in your task. Do not reformat or refactor other areas.
4. **Meta API:** follow the facts in `03`; if a detail matters and isn't there, say which docs page to check rather than guessing. Base URL `https://api.meta.ai/v1`, key from `MODEL_API_KEY` passed explicitly. Never use `-contributor` model IDs. Set `strict: true` and `reasoning_effort: "low"` for extraction; token cap ≥ 4,000; treat truncated finishes as failures. Never send audio to Spark.
5. **Security:** API keys only on the server; never in the browser, logs, commits or query strings. Realtime voice authenticates in the first WebSocket frame via the server relay.
6. **Exact maths:** use `fractions.Fraction`; a wrong number can never be coded Correct.
7. **Copy:** never write "can't be fooled", "calibrated", "proves understanding", "first", or hiring claims. Internal probabilities are "model estimates (assumed likelihoods)".
8. **Record/replay** every live model call during development; replay mode must work without a key.
9. **Never open, print or quote `.env`** or any file containing keys. If a task needs the key, use `os.environ["MODEL_API_KEY"]` in code; never read its value.
10. **Model modes:** the app's runtime calls use Standard IDs only (`muse-spark-1.3`, never `-contributor`). Coding tools (e.g. Muse Code) may run in Contributor mode on this repo, but never paste tester answers, recordings or personal data into any coding session.
11. **Small commits** with clear messages. End every session by listing which exit tests in `04` pass and which fail, with the exact command used.
