# 01 — Product spec

## One-liner and promise
**Unbluffable** — the interview that checks the maths, not the confidence.
Tagline: **"Sounding right isn't the same as being right."**
Quant-pack claim (only if the Monday gate passes): "The interviewer that hears your mistake before you finish the sentence."

Vision (pitch and roadmap only): one interview engine for every high-stakes interview — quant, software and cloud engineering, medicine, PhD, Oxbridge — checking answers against exact maths, running code, or expert rubrics; content from permitted web sources and verified, anonymous professionals paid for **original** questions and rubrics (never employers' confidential questions).

## What is built (committed)
**Quant pack:** probability interview puzzles (conditional probability / Bayes), three templates with fresh numbers, a "same puzzle, new numbers" twin, exact checks, voice and text.

Optional only if ahead by Friday, in this order: (1) a small "which model did what" panel on each turn (model, latency, cost); (2) a low/medium/high reasoning-effort comparison in the results; (3) Monte Carlo cross-check; (4) software-engineering pack. Pack builder: roadmap slide only.

## Screens and flows

### Landing (the hook — first 20 seconds)
- Title, tagline, and the quant interview card with the **mic ready**.
- If the visitor doesn't speak within 3 s, a **replay** plays (labelled "recorded run"):
  - Candidate: "…so if you test positive, you're about 90 percent likely to have it."
  - Interviewer: "Careful. 90% is the chance a sick person tests positive, not the chance that someone who tests positive is sick. Out of 2,000 people, how many healthy people also test positive?"
- A correct statement such as "the test has 90% sensitivity" must **never** trigger a challenge.
- Small switcher: "Quant (live)" and "More interviews coming" (roadmap).

### Spot the bluff (second card)
- One puzzle on screen. Two candidates answer **as audio with transcripts** (your own recorded voice, labelled); both give the right number. Who bluffs is randomised.
- Visitor taps the one they think is bluffing.
- "Same puzzle, new numbers" plays: one recomputes, the other repeats the old figure.
- First reveal: the verdict label and a single ✗. "Show the working" expands: quoted words, exact checks, the label path.
- Beside it: "Same answer sent to a plain chatbot on [date] — prompt linked" (saved run; choose the run by a stated rule, e.g. the modal verdict of 5 runs; show whatever it said).

### Interview (the core)
1. A puzzle appears (text). The user answers by **voice (mic button)** or **text**.
2. Voice: transcript appears live (realtime) or after speaking (fallback); the user can edit it before it is scored.
3. Challenge: mid-sentence if the gate passed, otherwise right after the completed answer.
4. The engine picks the next question (twin or a new puzzle) by information gain (`02`).
5. Stops at a label (after ≥2 answers) or after 4 questions.
6. End card: label, the quoted evidence, one practice tip for the diagnosed error.

### Labels (the only verdict vocabulary)
- **Evidence supports understanding**
- **Misconception detected** (names it, e.g. "transposed conditional")
- **Understanding not shown**
- **More evidence needed**
Never show a percentage as "the chance you understand". Internal probabilities may appear only in an expandable "model estimate (assumed likelihoods)" panel.

### Always-on behaviour
- Hosted link, no login. Works on phone and Safari.
- **Replay mode** (labelled recorded real runs) works without an API key.
- If spend caps trip: banner + no-model fallback (exact checks + new numbers, typed numbers only).
- Prompt-injection text in answers is quoted and ignored.
- Delivery (accent, pace, confidence of voice) is never scored.

## Copy rules
- Plain words. One sentence per screen element.
- Allowed: "checks the maths", "asks the same puzzle with new numbers", "model estimate".
- Forbidden: "can't be fooled", "calibrated", "proves understanding", "first", hiring claims.
