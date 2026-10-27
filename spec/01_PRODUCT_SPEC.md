# 01 — Product spec

## One-liner and promise
**Unbluffable** — the interview that checks the maths, not the confidence.
Tagline: **"Sounding right isn't the same as being right."**
Quant-pack claim (only if the Monday gate passes): "The interviewer that hears your mistake before you finish the sentence."

Vision (pitch and roadmap only): one interview engine for every high-stakes interview — quant, software and cloud engineering, medicine, PhD, Oxbridge — checking answers against exact maths, running code, or expert rubrics; content from permitted web sources and verified, anonymous professionals paid for **original** questions and rubrics (never employers' confidential questions).

## Impact (30% of the score): who benefits
Candidates facing high-stakes interviews (quant, software, engineering, medical-school, PhD, Oxbridge) without access to a coach who pushes back on their reasoning: students outside target universities, first-generation applicants, anyone who can't pay for mock interviews. Theme: **Build for Your World** (the builder prepares for these interviews firsthand); name the theme explicitly in the video, README and submission form. Evidence of impact comes from real users (see `05`, human testers), not only from benchmarks.

## Positioning against the organisers' anti-project list
Not an "AI for Education" chatbot: Unbluffable is a voice-first interviewer with a deterministic verification engine (exact maths, adaptive Bayesian question selection, live challenge of committed claims). Candidate-side practice only: not a job-application screener, never used to assess or rank candidates. No medical advice anywhere (the flagship is framed as fraud detection). Always lead with what a chatbot cannot do: challenge the exact number a candidate committed to, verify numbers exactly, re-test with new numbers, and count every hint.

## What is built (committed)
**Quant pack:** probability interview puzzles (conditional probability / Bayes), three templates with fresh numbers, a "same puzzle, new numbers" twin, exact checks, voice and text.

**Committed (Meta tooling is 25% of the score):** a small "which model did what" panel on each turn (model, job, latency, cost), visible in the demo.

Optional only if ahead by Friday, in this order: (0) a hosted, more natural interviewer voice (e.g. a Meta open-weights speech model on a sponsor's GPUs; quality unverified), behind a flag with the browser voice as fallback; (2) a low/medium/high reasoning-effort comparison in the results; (3) Monte Carlo cross-check; (4) software-engineering pack. Pack builder: roadmap slide only.

## Screens and flows

### Landing (the hook — first 20 seconds)
- Title, tagline, and the quant interview card with the **mic ready**.
- If the visitor doesn't speak within 3 s, a **replay** plays (labelled "recorded run"):
  - Candidate: "…so if a transaction gets flagged, it's about 90 percent likely to be fraud."
  - Interviewer: "Careful. 90% is the chance a fraudulent transaction gets flagged, not the chance a flagged transaction is fraud. Out of 2,000 transactions, how many genuine ones get flagged too?"
- A correct restated given such as "the detector catches 90% of fraud" must **never** trigger a challenge.
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
3. Challenge right after the completed answer (decision log 1b). The challenge is a **Socratic question about the candidate's own reasoning**, never the answer (see "Nudges, help and escalation"). The candidate may re-answer once.
4. At any point the candidate can ask for help or ask a clarifying question; the interviewer also offers help if they are stuck past the time guide.
5. The engine picks the next question (twin or a new puzzle) by information gain (`02`).
6. Stops at a label (after ≥2 answers) or after 4 questions. If the label is "Evidence supports understanding" with at most a light hint, the interviewer **escalates** with up to two harder follow-ups on the same scenario instead of stopping.
7. End card: label, the quoted evidence, hints used, time vs guide, recovery after challenge (yes/no), level reached (1–3), one practice tip for the diagnosed error.

### Nudges, help and escalation (committed; decision log 3)
Real quant interviews push back, give hints and get harder. Unbluffable does the same, and every bit of help is visible and counted.
- **Nudge (after a wrong or vague answer):** a question about the candidate's reasoning, chosen by the diagnosed error, e.g. transposed conditional: *"You said 90%. Is that the chance a flag is fraud, or the chance fraud gets flagged?"*; base-rate neglect: *"Out of 2,000 transactions, how many genuine ones get flagged?"*; other wrong: *"Walk me through how you got that number."* Never states the answer or the next step's number. One re-answer allowed; it is reported as "recovered after challenge" and does **not** change the evidence from the first answer.
- **Help on request:** "Can I get a hint?" / "Is it okay if I ask for help?" → *"Sure, what are you stuck on?"* → the interviewer gives the hint that matches what they say. Hints come from a fixed three-step ladder per template (H1 framing, H2 structure, H3 last step); Muse Spark only chooses which hint fits and may rephrase it, and code rejects any hint text containing the answer or a number that isn't a given.
- **Help offered:** if there is no committed answer by 60% of the time guide, the interviewer asks *"Is there anything you're stuck on?"* A "no" costs nothing.
- **Clarifying questions** ("are the two checks independent?") are answered from the template's fixed assumptions and never count as a hint.
- **What counts against the candidate:** hints weaken the evidence from the next answer (H1 slightly, H3 most; `02` §7). Time vs the guide (new puzzle 2 min, twin 1 min, follow-up 1.5 min) is shown on the end card but does not change the label. Asking many hints shows up plainly in "hints used".
- **Escalation:** strong candidates get harder follow-ups on the same scenario: level 2 = a second, independent piece of evidence agrees; level 3 = it disagrees (`02` §7). "Level reached" is shown separately from the label.
- Positioning: hints are an interviewer's hints with a cost, not tutoring; the full method is shown only on the end card.

### Interviewer voice (committed)
- The interviewer **speaks everything**: each question, each challenge, the follow-up, and the verdict. The same text appears on screen.
- Uses the browser's speech synthesis (Meta has no text-to-speech model; disclose this). Prefer the best natural-sounding English voice available (Chrome/Edge "Natural"/"Online" voices on Windows), with a fixed fallback order.
- Mic input is muted while the interviewer speaks (no echo). Headphones recommended on the landing page.
- A visible "mute interviewer" toggle; text-only mode always works.
- Interruptions use the same voice and start immediately (browser speech has near-zero start-up delay).

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
