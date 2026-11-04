# EXPLORATORY, not pre-registered (decision log 47, registered before any call); 39 of 40 items model-written

Status: **complete**. Items `eval\items_draft.json` sha256 `b9aeb7f1dee995006df37c987f2c910cf781c4b3ddb9724df11ed8a90289a6d7`; muse-spark-1.3 (meta_api); 3 runs; commit `cc792ea412722b6c8c02aeffe24d41ae0fe3a032`; 2026-11-04T13:45:38+00:00.

Items flagged (does_not_understand) by the majority of the runs; per run in brackets.

| Category | Items | Careful Muse Spark, first answer only | Unbluffable (original and new numbers) |
| --- | --- | --- | --- |
| recited | 10 | 10 / 10 (10, 10, 10) | 10 / 10 (10, 10, 10) |
| misconception | 10 | 10 / 10 (10, 10, 10) | 10 / 10 (10, 10, 10) |
| arithmetic slip | 5 | 5 / 5 (5, 4, 5) | 5 / 5 (5, 5, 5) |
| correct | 15 | 14 / 15 (14, 13, 13) | 1 / 15 (1, 1, 1) |

Recited items, majority verdict:

- e12: careful_first_only does_not_understand; unbluffable does_not_understand
- e14: careful_first_only does_not_understand; unbluffable does_not_understand
- e17: careful_first_only does_not_understand; unbluffable does_not_understand
- e22: careful_first_only does_not_understand; unbluffable does_not_understand
- e28: careful_first_only does_not_understand; unbluffable does_not_understand
- e32: careful_first_only does_not_understand; unbluffable does_not_understand
- e33: careful_first_only does_not_understand; unbluffable does_not_understand
- e34: careful_first_only does_not_understand; unbluffable does_not_understand
- e37: careful_first_only does_not_understand; unbluffable does_not_understand
- e39: careful_first_only does_not_understand; unbluffable does_not_understand

Careful Muse Spark, first answer only: verdict changed across runs on 5 item(s) ['e07', 'e20', 'e23', 'e27', 'e38']

Unbluffable (original and new numbers): verdict changed across runs on 0 item(s) 

Recited items, exact McNemar (exploratory): Unbluffable only 0, careful_first_only only 0, p = 1

---

*Added after the run (not part of the script's output):*

- Correct items, exact McNemar on the majority verdicts (exploratory, computed with `scripts/evidence/stats.py`): flagged by careful_first_only only 13, by Unbluffable only 0 (both flagged e05), p = 1/4096 ≈ 0.00024.
- The run's commit `cc792ea` was later rebased onto main as `3ec6adf`. The script, harness, prompts and item file are byte-identical between the two.
- `results.json` here is the script's `results.json`, copied from `eval/raw/exploratory-first-only/` (that folder is gitignored).
