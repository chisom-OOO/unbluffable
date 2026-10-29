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
