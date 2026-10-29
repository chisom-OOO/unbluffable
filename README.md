# Unbluffable

**Sounding right isn't the same as being right.**

A spoken mock interviewer for high-stakes technical interviews. You answer out loud, hands-free. Unbluffable pulls out the number you committed to, quotes your own words back to you, checks the maths exactly in code, and challenges a wrong answer with a question instead of an explanation. Then it asks the same puzzle again with new numbers, to tell understanding from memorisation.

Built solo for the **Meta Global AI Developer Hackathon**, Indie track, theme **Build for Your World**: I'm preparing for quant interviews myself, and most candidates never get an interviewer who pushes back on their reasoning.

> **Status (29 Oct 2026):** the hands-free voice interview, exact checking, Bayesian scoring and the end-of-interview report work end to end. In progress this week: a verified question forge across topics and a measured comparison against a carefully prompted chatbot (see [What's next](#whats-next)). Results go here only once they are measured.

## Why

A fluent answer and a correct answer sound the same. A chatbot can hand anyone the right number, and a practice tool that grades on fluency can't tell whether you understood it. Real interviewers check: they ask why, they push on a wrong step, and they change the numbers. Unbluffable is built to do the same, out loud, for anyone without access to a coach.

## What it does

- **Hands-free spoken interview.** One tap starts it. The interviewer speaks each question, the candidate talks it through, and the app decides when the answer is finished from what was said, not from a fixed pause. A silence prompt and an optional Done button are fallbacks. Typed answers work too.
- **Exact checking.** The model extracts the committed answer and supporting quotes, limited to the candidate's own words. The numbers are checked with exact fractions in code, never by a model.
- **Socratic challenge.** A committed wrong answer gets a question that points at the step, not the solution. Nudges and hints are allowed, and the score counts the help it took.
- **Same puzzle, new numbers.** A second version of the question with different numbers separates someone who worked it out from someone who remembered an answer.
- **Evidence-based scoring.** A Bayesian engine weighs each final answer, discounted by the help used, and stops once the evidence is clear. The label is one of: *Evidence supports understanding*, *Misconception detected*, *Understanding not shown*, *More evidence needed*.
- **In-app report.** A headline label, one tab per question, the candidate's quoted words beside the exact value, the help taken and time against the guide.
- **Which model did what.** Each turn shows which model ran, for which job, with latency and cost.
- **Privacy.** Audio and video are never saved; answer text is kept only with consent. The camera preview is local only, off by default.

## Meta models and their roles

| Model | Where it runs | Job |
| --- | --- | --- |
| Muse Voice Transcribe (`muse-voice-transcribe-1.0`) | Meta Model API, realtime | Live speech-to-text for the hands-free interview |
| Muse Spark (`muse-spark-1.3`) | Meta Model API | Extracts the committed answer and verbatim quotes; judges whether an answer is finished |
| Muse Spark Open (`muse-spark-open-1026`, open weights) | Baseten | The same reasoning jobs on the hosted app; author of the question forge (in progress) |
| Exact maths | Our code | Every number check, every score |

**Why open weights.** From our cloud host, Meta's API listed no Muse Spark models for our key: `GET /v1/models` returned HTTP 200 with an empty list, while the same key from a UK connection listed 9 models. Moving every reasoning call on the hosted app to Muse Spark Open kept it deployable. On a 10-case latency probe, Spark Open had a median of 1.59 s (max 3.95 s) against 0.98 s (max 1.90 s) for Muse Spark at minimal effort, and gave the same commitment and number as Muse Spark on all 10 cases. Transcription stays on Muse Voice Transcribe.

## How it works

```
voice (browser) ──► Muse Voice Transcribe (realtime) ──► live transcript
                                                          │
                     end-of-answer check: rules, then Muse Spark / Spark Open
                                                          │
                     Muse Spark / Spark Open: committed number + verbatim quotes
                                                          │
                     code: exact check, misconception match, help load
                                                          │
                     Bayesian engine (Sound / Misconception / Gap) ──► next question or stop
                                                          │
                     interviewer speaks: acknowledgement, challenge, nudge or next puzzle
```

- **Turn-taking.** After a short pause, deterministic cues decide first ("that's my answer", a trailing "so…"), and only unclear cases go to Muse Spark. If the candidate goes quiet for about 8 s, a fast check ends the turn if a number has been committed, and otherwise asks them to talk it through.
- **Help accounting.** Each hint or nudge is scored by how many solution steps it gives away beyond where the candidate already was (help load H). A correct answer after help counts for less: its evidence weight is w = 2 / (2 + H), and a challenge counts as one more step (spec/02 §7).
- **No model grades a number.** Models extract and phrase; code computes. Quotes are kept only if they appear word for word in the transcript.

## Measured so far

| What | Result |
| --- | --- |
| Interrupting mid-sentence (realtime keyword rules) | 2/10 wrong answers caught on the first gate. Rules widened from the failure types reached 8/10 on those clips but **1/10 on 30 new held-out clips**, with 0/20 false challenges in both runs. Dropped in favour of challenging right after the answer ([decision log](spec/DECISION_LOG.md) rows 1–1b). |
| End-of-answer detection, 60 recorded clips | **0 early cut-offs.** 32/60 completed exactly once; every miss was the app waiting too long, never interrupting. A silence check was added since (rows 11–12). |
| Last word to spoken acknowledgement | About 2 s in a timed run, most of it one Muse Spark call |
| Muse Spark Open vs Muse Spark | Same result on 10/10 probe cases; median 1.59 s vs 0.98 s |
| Automated tests | 450+ (pytest), including pinned values for the engine maths |

Every change from the original plan is in the [decision log](spec/DECISION_LOG.md) with the evidence that forced it, including the things that failed.

## What's next

These are in progress and are **not** claimed as results yet:

- **Question forge across topics.** Muse Spark Open turns questions from a pre-existing bank of 5,921 interview and online-assessment questions into reworded templates with an exact solver, a separately written simulation and named wrong-method values. A template is accepted only if the solver reproduces the stored answer, the simulation agrees, and Muse Spark solves a new-number version blind and matches. The bank itself is not in this repository.
- **Careful-chatbot comparison.** A pre-registered test on frozen answers: plain Muse Spark, carefully prompted Muse Spark, carefully prompted Muse Spark given the answer key, and Unbluffable, all on the same model, three runs each.
- **Real users** from a university quant society, with consent.

## Run it locally

Requirements: Python 3.12, ffmpeg (for uploaded audio files), and a Meta Model API key.

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"        # Windows: .venv\Scripts\pip install -e ".[dev]"
export MODEL_API_KEY=...                  # Windows PowerShell: $env:MODEL_API_KEY = "..."
.venv/bin/python -m uvicorn app.main:app --port 8000
```

Open `http://localhost:8000/ui` and start an interview. Use headphones if you want to talk over the interviewer; without them the mic is muted while it speaks.

To send every reasoning call to Muse Spark Open instead, also set `LLM_BACKEND=open_weights` and `BASETEN_API_KEY`.

Run the tests (no API key needed; they use fakes):

```
.venv/bin/python -m pytest -q
```

Docker: `docker build -t unbluffable .` then `docker run -p 8000:8000 -e MODEL_API_KEY=... unbluffable`.

## Repository

| Path | Contents |
| --- | --- |
| `app/` | FastAPI server, Exam Room interview, report, voice routes |
| `engine/` | Puzzle templates, exact checking, Bayesian engine, help discount |
| `llm/` | Model clients (Meta Model API and open weights), structured extraction, record/replay |
| `voice/` | Realtime transcription relay, end-of-answer detection |
| `content/` | Likelihood tables |
| `docs/` | Measured capability sheet for the Meta APIs |
| `spec/` | The plan written before kickoff, and the decision log |
| `scripts/` | Latency probes and the turn-taking gate harness |
| `tests/` | Automated tests |

## Disclosures and limits

- **Prior work:** the specification in `spec/` was written before kickoff as a plan. All code was written after kickoff (26 Oct 2026); the commit history shows it. Built with AI coding assistants (Claude Code, Codex, Muse Code).
- **Probabilities are model estimates.** The engine's likelihoods are stated assumptions (`content/likelihoods.yaml`), not calibrated measurements.
- **Turn-taking can wait too long.** When it does, the silence prompt or the Done button moves things on.
- **Interview practice, not a tutor or a hiring tool.** It's built for candidates to practise.
