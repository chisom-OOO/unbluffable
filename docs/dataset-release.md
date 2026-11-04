# Numeric question dataset release

Public dataset: https://huggingface.co/datasets/unbluff/unbluffable-numeric-interview-questions

Dataset commit: `a9603a15e10333407273b5ca24329e7a9f9add33`.

Source project commit: `5db4b185d28eeee3fa89082dee6aeeca00bb115e`.

The release has 600 questions from 12 families, with 150 questions in each of quant, investment banking, consulting and software engineering. Every stored variant of each selected family is included. The family IDs, source-file hashes and corpus checksum are in the published manifest.

## Release files

- `data/questions.jsonl`: 600 question variants with exact rational answers and parameter metadata.
- `README.md`: Hugging Face dataset card, generation provenance, intended use and limitations.
- `LICENSE`: MIT licence and the source project's copyright notice.
- `manifest.json`: selection, immutable source commit, source-file SHA-256 hashes and corpus checksum.
- `validate_dataset.py`: offline numerical checks using Python's standard library.
- `validation_report.json`: result of the release validation.

After downloading or cloning the dataset, run:

```bash
python validate_dataset.py
```

The release result is **600/600 exact answers recomputed from parameters**, with 1,336 stored wrong values checked for collisions with the correct answer. The JSONL SHA-256 is `647eb45d35b303f438cf3f0ce1393dca687ef3e6d67697cc3f86b1e1000960b8`.

The numerical formulae cover conditional and discrete probability, operating profit, breakeven, stated-assumption market sizing, working-capital cash effects, enterprise value, valuation multiples, sliding windows, largest-value selection and sums of consecutive slices.

## Scope of the evidence

Question and variant generation is disclosed as ChatGPT, with the selected `qe_` families written by Claude. Original solver authorship is recorded as Muse Spark Open on Baseten. The release validator was prepared with Codex and implements the selected answer computations from their parameters.

Source review status is retained, including `pending_builder_review`. This release does not assert completed human review. It does not reproduce the original forge run or bundle its original solver source. Wrong-method names and intermediate steps are retained annotations; their algorithms and semantic correctness are outside the release validation.

The public corpus has no held-out split. Related variants should remain grouped by family in any future training/evaluation split. It contains no candidate answers, recordings, private source bank, behavioural transcripts or user feedback. It does not measure benefits to live candidates or compare interview outcomes.
