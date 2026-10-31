# Evidence harness

Pre-registered comparison (decision log 15). Four arms judge the same frozen items on
one backend, `--runs` times each (3 by default):

| Arm | What it sees |
|---|---|
| `plain` | `prompts/plain.txt`, both questions and both answers |
| `careful` | `prompts/careful.txt`, the same |
| `careful_answers` | `prompts/careful_with_answers.txt`, plus the stored exact answer to each question |
| `unbluffable` | the Exam Room's own extraction (`app.interview_session.VoiceAnalyzer`), exact checks and engine label |

Unbluffable's verdict is `understands` only for "Evidence supports understanding";
any other label is `does_not_understand`. A failed call is `error`: never correct and
never a flag.

```
python scripts/evidence/harness.py --items PATH --backend meta_api --runs 3 \
    [--expect-items-sha256 HASH] [--out eval/raw/evidence]
```

A live run refuses uncommitted changes to the prompts, `harness.py` or `stats.py`, and
records the commit, the item file's sha256 and each prompt's sha256. Calls are recorded
under `recordings/evidence/` (git-ignored). Tests use fakes and replay only.

## Making the items (freeze Saturday 14:00)

```
python scripts/evidence/make_items.py      # eval/items_draft.json: 40 pairs, empty transcripts
python scripts/evidence/fill_items.py      # type or paste transcripts; checked, saved after each item, resumable
python scripts/evidence/freeze.py          # validates; prints the sha256 and the exact harness command
python scripts/evidence/dry_run.py         # every arm on a fake model, plus a live cost estimate
```

`make_items.py` takes 40 Quant forge families with verified misconceptions (one item per
family, spread across topics), an interview-friendly original instance, and the engine's
own twin choice (`engine.bank.twin_choice`, aimed at the item's misconception for that
category). Categories, checked exactly on the last number each transcript states:

| Category | Count | Original | Twin | Label |
|---|---|---|---|---|
| memorised | 10 | exact answer | the original's answer again, or another wrong number | does_not_understand |
| misconception | 10 | the item's named wrong value | the same mistake's value | does_not_understand |
| slip | 5 | exact answer | a wrong number that is not a named error or the original's answer | understands |
| correct | 15 | exact answer | exact answer | understands |

Each item also records `category`, `source` (builder, tester or model-written), the
family's `topic` and `difficulty`, and the instance indices. The slip label is a choice
to confirm before the freeze (`SLIP_LABEL` in `itemcheck.py`).

The dry run's cost basis: about 4 characters per input token, the forge budgeting prices
(USD 1.25 / 4.25 per million input / output tokens), 500 output tokens per call, and an
upper bound at the 4,000-token cap. For 4 arms x 3 runs x 40 items that is 840 calls.

## Item file

```json
{"version": 1, "items": [{
  "id": "e01",
  "label": "understands",
  "template_id": "fx_dice_total",
  "original": {"question": {<forge instance>}, "transcript": "..."},
  "twin":     {"question": {<forge instance>}, "transcript": "..."}
}]}
```

`label` is `understands` or `does_not_understand`. A forge instance has `text`,
`params`, `answer` (exact string), `tolerance`, `wrong` and `steps`, as in
`content/forge/`.

## Outputs

`results.json` and `results.md` report the following:
- Each arm's majority-verdict accuracy and its accuracy per run.
- The false-flag rate on items labelled `understands`.
- The verdict flip rate across runs.
- Exact McNemar of Unbluffable against each other arm, by majority and per run.
- The headline rule. If careful Spark with stored answers is within 2 items of Unbluffable, the headline becomes "a careful chatbot needs a verified answer key; the forge supplies one".
