<div align="center">

# Unbluffable

### Sounding right isn't the same as being right.

A spoken mock interviewer that hears your answer, quotes your words back,<br/>
checks your numbers exactly and pushes back like a real interviewer,<br/>
so anyone can know what the room feels like before they're in it.

![Meta Global AI Developer Hackathon](https://img.shields.io/badge/Meta_Global_AI_Developer_Hackathon-Indie_track-0866FF)
![Theme](https://img.shields.io/badge/theme-Build_for_Your_World-0866FF)
![Open weights](https://img.shields.io/badge/open_weights-Muse_Spark_Open-6E40C9)
![Python](https://img.shields.io/badge/python-3.12-3776AB)
[![Tests](https://github.com/chisom-OOO/unbluffable/actions/workflows/tests.yml/badge.svg)](https://github.com/chisom-OOO/unbluffable/actions/workflows/tests.yml)

**▶ Live:** https://unbluffable-ptz1.onrender.com (laptop or iPad, Chrome or Safari, allow camera and mic; first load can take ~30 s)<br/>
**▶ 3-minute video:** VIDEO_LINK_TODO

[How it works](#how-it-works) · [Meta models](#meta-models-used) · [Measured so far](#measured-so-far) · [Run it](#run-it-locally) · [Decision log](spec/DECISION_LOG.md)

</div>

---

Voice mock interviews for quant, banking, consulting and software roles. You answer aloud; code checks every number exactly, the interviewer questions the number you committed to, then asks the same puzzle with new numbers chosen so the suspected mistake gives a clearly different answer.

> [!NOTE]
> **Prior work.** The specification in `spec/` was written before kickoff as a plan. All code was written after kickoff on 26 Oct 2026, and the commit history shows it. Built with AI coding assistants (Claude Code, Codex, Muse Code). More in [Disclosures and limits](#disclosures-and-limits).

### Judge path in 2 minutes

1. Open the [live app](https://unbluffable-ptz1.onrender.com) and press the sample replay on the landing page.
2. Start a quant interview, allow camera and mic, and give a wrong number on purpose.
3. Listen to the interviewer question that exact number, then answer the same puzzle with new numbers. Open the receipt to see your quoted words beside the exact computation.

### At a glance for judges

| Criterion | What to look at | Where |
| --- | --- | --- |
| **Impact** | Interview practice that questions the number you said, for people with no coach or network to practise against; four tracks | [Why](#why), [live app](https://unbluffable-ptz1.onrender.com) |
| **Meta tooling** | Three Meta models with separate jobs: Voice Transcribe hears, Spark extracts and quotes, Spark Open (open weights) runs the hosted app and wrote the question families' solvers | [Meta models](#meta-models-used), `llm/`, `voice/`, `forge/` |
| **Technical depth** | Exact maths with fractions (no model grades a number), a Bayesian engine with a help discount, held-out gate results, a pre-registered comparison, 1,200+ tests | `engine/`, [Measured so far](#measured-so-far), [decision log](spec/DECISION_LOG.md) |
| **Demo** | Live app, sample replays per track, the 3-minute video | Links above, [screenshots](#screenshots) |

## Screenshots

| Landing | Interview room, mid-challenge | Report |
| --- | --- | --- |
| ![Landing page: the headline, a track picker and the sample exchange ending with the same puzzle with new numbers](docs/assets/landing.png) | ![Interview room: the candidate said 11/24, the code marked it not the exact answer, and the interviewer asks how they got there](docs/assets/room-challenge.png) | ![Interview report: the label, the counts of challenges and help, and each question's quoted words beside the exact value](docs/assets/report.png) |

<sub>Taken from the local app in replay mode, with no key. The room and report show a scripted session from the test suite, not a real user.</sub>

## Why

I struggled in interviews. Not because I didn't know the material, but because I'd never been in the room: never had someone stop me mid-answer, question the number I'd just committed to, and ask it again with different numbers.

Some candidates get that practice through coaches, paid prep or people who've been through it. Most don't. They find out what a real interview is like by sitting one.

I started building this for quant interviews, my own field. But the problem isn't quant. Banking, consulting and software interviews work the same way: you think out loud, commit to an answer, and get pushed on it. Quant, investment banking, consulting and software engineering are all live.

**It's the interviewer you'd have if you had the connections.** Built for the theme **Build for Your World**.

## What it does

| | |
| --- | --- |
| **Four tracks** | Quant, investment banking, consulting and software engineering, each with its own topics and the same interviewer. |
| **Behavioural questions** | For banking and consulting: "tell me about a time…" and "what would you do if…". Your STAR funnel is filled with your own quoted words, the interviewer probes the weakest step, and your follow-up is checked against your first telling. Model-judged, and labelled that way. |
| **Hands-free spoken interview** | One tap starts it. The interviewer speaks, you talk it through, and the app decides you've finished from what you said, not from a fixed pause. The interviewer's voice is your browser's built-in speech synthesis. A silence prompt and an optional Done button are fallbacks. Camera and microphone are on, as in a real interview; a typed practice mode is there for anyone who can't use them, labelled *not exam conditions*. |
| **Exact checking** | The model extracts the answer you committed to and quotes your own words. Every number is checked with exact fractions in code, never by a model. |
| **Challenge on the step** | A committed wrong answer gets a question that points at the step, not the solution. Nudges and hints are allowed, and the score counts the help it took. |
| **Same puzzle, new numbers** | A second version with different numbers separates someone who worked it out from someone who remembered an answer. |
| **Numbers chosen to expose your mistake** | When the interviewer suspects a specific mistake, it picks the new numbers where that mistake gives a clearly different answer from the right method, and says why these numbers. |
| **Live evidence meter** | The Sound / Misconception / Gap estimate updates after every scored answer, with one line on what the next answer would change. |
| **Receipts** | Every challenge and every report line opens to show your exact words beside the exact computation: the value read, the check, and the known wrong methods. |
| **Targeted drill** | From the report, a short drill aims new questions at a detected misconception, asks questions only, then checks with fresh numbers: *Cleared* or *Still showing*. |
| **Evidence-based scoring** | A Bayesian engine weighs each final answer, discounted by the help used, and stops when the evidence is clear: *Evidence supports understanding*, *Misconception detected*, *Understanding not shown* or *More evidence needed*. |
| **In-app report** | A headline label, one tab per question, your quoted words beside the exact value, the help taken and time against the guide. |
| **Which model did what** | Every turn shows which model ran, for which job, with latency and cost. |
| **Privacy** | Audio and video are never saved; answer text is kept only with consent. The camera self-view stays on this device: never recorded, uploaded or sent to a model. |

## Bring your own question

Upload a screenshot or photo of one question from your own notes or a practice set, or paste it ([/ui/byoq](https://unbluffable-ptz1.onrender.com/ui/byoq)). A Meta model reads the image into text you can correct; it is never asked for the answer, and the image is read once and not stored. The question is practised only if it passes a check in code: two separately written programs (a solver from each of two models, or on the hosted app a solver and an exhaustive simulation) must agree exactly, as fractions, on your question and on at least 10 versions with new numbers, and match the answer in your notes if they show one. Common wrong methods are kept only if they give different values. Then it runs in the normal room: the same challenge of the number you commit to, then the same puzzle with new numbers. The report says "Your question · checked in code on N variants". A question that can't be checked isn't scored, and your own questions never count toward your rating ([decision log 38](spec/DECISION_LOG.md)). Use your own notes or practice questions, not real interview or assessment questions.

## How it works

```mermaid
flowchart LR
    A(["Candidate<br/>speaks"]) --> B["Muse Voice Transcribe<br/><i>live transcript</i>"]
    B --> C{"Finished?<br/><i>rules first,<br/>Muse Spark if unclear</i>"}
    C -->|not yet| B
    C -->|yes| D["Muse Spark / Spark Open<br/><i>committed number +<br/>verbatim quotes</i>"]
    D --> E["Exact check<br/><i>fractions · misconception ·<br/>help load</i>"]
    E --> F["Bayesian engine<br/><i>Sound · Misconception · Gap</i>"]
    F --> G(["Interviewer speaks<br/><i>challenge · nudge ·<br/>new numbers · report</i>"])
    G -.->|next turn| A

    classDef person fill:#F3EEFF,stroke:#6E40C9,color:#1F1040,stroke-width:1.5px
    classDef meta fill:#E7F0FF,stroke:#0866FF,color:#0B1F44,stroke-width:1.5px
    classDef code fill:#EAF7EE,stroke:#2EA043,color:#0F2E18,stroke-width:1.5px
    class A,G person
    class B,D meta
    class C,E,F code
```

<sub>Purple: people · Blue: Meta models · Green: our code</sub>

One answer, start to finish:

```mermaid
sequenceDiagram
    autonumber
    actor Cand as Candidate
    participant App as Unbluffable
    participant Spark as Muse Spark
    participant Code as Exact check

    App->>Cand: Speaks the question
    Cand->>App: Talks it through, commits to a number
    App->>Spark: Has the candidate finished?
    Spark-->>App: Finished
    App->>Cand: Neutral acknowledgement ("Got it.")
    App->>Spark: What number was committed? Quote the words
    Spark-->>App: Number + verbatim quote
    App->>Code: Compare with the exact answer
    Code-->>App: Wrong, matches a known misconception
    App->>Cand: Challenge aimed at the step
    Cand->>App: Recovers
    App->>Cand: Same puzzle, new numbers
```

- **Turn-taking.** After a short pause, deterministic cues decide first ("that's my answer", a trailing "so…"), and only unclear cases go to the model. If you go quiet for about 8 s, a fast check ends the turn if you've committed to a number, and otherwise asks you to talk it through.
- **Help accounting.** Each hint or nudge is scored by how many solution steps it gives away beyond where you already were (help load H). A correct answer after help counts for less: its evidence weight is w = 2 / (2 + H), and needing a challenge counts as one more step ([spec/02 §7](spec/02_ENGINE_SPEC.md)).
- **No model grades a number.** Models extract and phrase; code computes. A quote is kept only if it appears word for word in your transcript.

## Meta models used

| Model | Runs on | Job |
| --- | --- | --- |
| **Muse Voice Transcribe** · `muse-voice-transcribe-1.0` | Meta Model API, realtime | Live speech-to-text for the hands-free interview |
| **Muse Spark** · `muse-spark-1.3` | Meta Model API | Extracts the committed answer and verbatim quotes, judges whether an answer is finished, judges behavioural answers (local runs). For Bring your own question (local runs), reads the uploaded image or pasted text into the question text (image input, strict JSON schema; it is not asked to solve it) and writes the second, independent solver that checks it |
| **Muse Spark Open** · `meta-models/muse-spark-open-1026` | Baseten (open weights) | Every reasoning call on the hosted app (`LLM_BACKEND=open_weights`), including judging behavioural answers and, for Bring your own question, reading the uploaded image and writing both of its checks (a solver and, in a separate call, an exhaustive simulation). In local runs it writes a BYOQ question's template, solver and wrong methods, all run in a sandbox, never in the web process. Offline, it wrote each question family's solver, wrong-method values and coding tests: a solver written from two worked examples, then run on every variant. A family ships only if its solver reproduces every stored answer in code. The questions, variants and stored answers were generated with ChatGPT |
| **Exact maths** | Our code | Every number check and every score |

### Why open weights

The hosted app runs on Muse Spark Open because, from our cloud host, Meta's API showed no Muse Spark models for our key: `GET /v1/models` returned HTTP 200 with an empty list, while the same key from a UK connection listed 9 models. Moving every reasoning call on the hosted app to Muse Spark Open kept it deployable. Transcription stays on Muse Voice Transcribe.

| Parity check | Muse Spark 1.3 | Muse Spark Open (Baseten) |
| --- | --- | --- |
| 10-case latency probe, median (max) | 0.98 s (1.90 s), minimal effort | 1.59 s (3.95 s) |
| Same commitment and number as Muse Spark, 10 cases | — | **10 / 10** |
| Run 1, Unbluffable's correct verdicts (below) | 34 / 40 | 35 / 40, no verdict changing across runs |

## Measured so far

| What | Result |
| --- | --- |
| **Interrupting mid-sentence** with realtime keyword rules | 2/10 wrong answers caught on the initial gate. Rules widened from the failure types reached 8/10 on those clips but **1/10 on 30 new held-out clips**, with 0/20 false challenges in both runs. We dropped it for a challenge right after the answer ([decision log](spec/DECISION_LOG.md) rows 1–1b). |
| **End-of-answer detection** on 60 recorded clips | **0 early cut-offs.** 32/60 completed exactly once; every miss was the app waiting too long, never interrupting. A silence check was added afterwards (rows 11–12). |
| **Last word to spoken acknowledgement** | About 2 s in a timed run, most of it one Muse Spark call |
| **Question families shipped** | **275** of 286 families attempted (decision log rows 19, 21–22 and 30) across four tracks (129 quant, 18 quant developer, 60 investment banking, 30 consulting, 38 software engineering), 50 or 75 variants each, plus 54 coding specs. For each family Muse Spark Open wrote a solver from two worked examples; the family ships only if that solver reproduces the stored answer on every variant (270 exactly, 5 within the stated tolerance). Families that missed any variant were not shipped, e.g. 2 of the 101 in the main quant pack. 230 families also have wrong-method values verified in code, which the interviewer uses to name a misconception. |
| **Automated tests** | 1,200+ (pytest, 1,224 in the last full run), including pinned values for the engine maths, plus five Node suites for the browser logic |

Every change from the original plan is in the [decision log](spec/DECISION_LOG.md), with the evidence that forced it, including what failed.

### Comparison against a carefully prompted chatbot (run 1)

Run 1 used frozen, model-written transcripts: every arm saw both the original and the new-numbers answer, and the bluffs were easy, so it could not test the live challenge.

Pre-registered and frozen before any model saw it ([decision log](spec/DECISION_LOG.md) rows 15, 31, 32; items in [`eval/items_draft.json`](eval/items_draft.json), sha256 `b9aeb7f1`). 40 answer pairs (an original question and its new-numbers twin): 15 correct, 10 recited from memory, 10 confident misconceptions, 5 arithmetic slips. Every arm saw the same transcripts, three runs each.

**Pre-registered headline:** Unbluffable 34 / 40 against a carefully prompted Muse Spark given the verified answers, 35 / 40. No significant difference.

| Arm | Correct verdicts | False flags on answers that show understanding |
| --- | --- | --- |
| Plain Muse Spark 1.3 | 39 / 40 | 5% |
| Carefully prompted Muse Spark | 34 / 40 | 25% |
| Carefully prompted, given the verified answers | 35 / 40 | 25% |
| **Unbluffable** (Muse Spark) | 34 / 40 | 30% |
| **Unbluffable on Muse Spark Open** | 35 / 40 | 25% |

**What it shows.** No arm is significantly better than another (exact McNemar, smallest p = 0.0625). Every arm caught every recited and every misconceived answer: the bluffs in this set were too easy to spot, because 39 of the 40 transcripts were written by a model (Claude) and give themselves away. The arms differ only on the five arithmetic slips, which Unbluffable marks as not yet shown in a frozen transcript; in a live interview it would challenge the number instead. One item labelled correct (e05) was scored Vague by Unbluffable. Replaying the recorded calls showed this was not a bug: the answer (22) was extracted correctly, but the item's transcript only read out the question's own figures before the number, with no reasoning, and Unbluffable codes a right number without supporting reasoning as Vague by design. The flaw is in that model-written item. Muse Spark Open coded the same reasoning as valid, so the open-weights arm scored it Correct. Unbluffable on open weights matched Unbluffable on Muse Spark, with no verdict changing across runs.

**What it doesn't show.** It doesn't test the live interview, where Unbluffable picks numbers that expose a suspected mistake and challenges the number you commit to.

Run 2 (pre-registered, decision log row 34): not run, because no testers were available before the deadline.

## Run it locally

**Needs:** Python 3.12, ffmpeg (for uploaded audio files) and a Meta Model API key.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
export MODEL_API_KEY=...
.venv/bin/python -m uvicorn app.main:app --port 8000
```

<details>
<summary>Windows PowerShell</summary>

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
$env:MODEL_API_KEY = "..."
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

</details>

Open **http://localhost:8000/ui** and start an interview. Wear headphones if you want to talk over the interviewer; without them the mic is muted while it speaks.

| Option | How |
| --- | --- |
| All reasoning calls on Muse Spark Open | Set `LLM_BACKEND=open_weights` and `BASETEN_API_KEY` |
| Run the tests (no key needed, uses fakes) | `.venv/bin/python -m pytest -q` |
| Docker | `docker build -t unbluffable .` then `docker run -p 8000:8000 -e MODEL_API_KEY=... unbluffable` |

## Repository

| Path | Contents |
| --- | --- |
| `app/` | FastAPI server, Exam Room interview, report, voice routes |
| `engine/` | Puzzle templates, exact checking, Bayesian engine, help discount |
| `llm/` | Model clients (Meta Model API and open weights), structured extraction, record/replay |
| `voice/` | Realtime transcription relay, end-of-answer detection |
| `content/` | Question families (`content/forge/`), coding specs, behavioural questions, likelihood tables |
| `docs/` | Measured capability sheet for the Meta APIs, README screenshots (`docs/assets/`) |
| `spec/` | The plan written before kickoff, and the decision log |
| `forge/` | Offline question forge: Muse Spark Open writes solvers and wrong-method values, code verifies them |
| `scripts/` | Latency probes, the turn-taking gate harness and the evidence harness (`scripts/evidence/`) |
| `tests/` | Automated tests |

## Disclosures and limits

- **Prior work.** The specification in `spec/` was written before kickoff as a plan; the commits before kickoff on 26 Oct are docs only, and their messages say so. All code was written after kickoff on 26 Oct 2026, and the commit history shows it. Built with AI coding assistants (Claude Code, Codex, Muse Code).
- **Question sets.** The quant, investment banking, consulting and software engineering question sets were generated by the builder with ChatGPT during the hackathon (30 Oct 2026).
- **Behavioural questions.** The 40 behavioural questions (with their answer signals, pitfalls and probes) were written with Claude during the hackathon (30 Oct 2026). Behavioural answers are judged by Muse Spark, labelled "model-judged, not exact", and never feed the readiness rating or the label. Their answers are re-checked in code as described above; ChatGPT is not used by the running app.
- **Probabilities are model estimates.** The engine's likelihoods are stated assumptions (`content/likelihoods.yaml`), not measured rates.
- **Turn-taking can wait too long.** When it does, the silence prompt or the Done button moves things on.
- **Interview practice for candidates.** It doesn't screen, rank or report on anyone.
