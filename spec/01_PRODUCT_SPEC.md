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
3. Challenge right after the completed answer (decision log 1b). The challenge is a **Socratic question about the candidate's own reasoning**, never the answer (see "Nudges, help and escalation"). The conversation continues with further nudges until they get there, ask to move on, or reach the round limit; only the **first** answer is scored.
4. At any point the candidate can ask for help or ask a clarifying question; the interviewer also offers help if they are stuck past the time guide.
5. The engine picks the next question (twin or a new puzzle) by information gain (`02`).
6. Stops at a label (after ≥2 answers) or after 4 questions. If the label is "Evidence supports understanding" with at most a light hint, the interviewer **escalates** with up to two harder follow-ups on the same scenario instead of stopping.
7. End card: label, the quoted evidence, hints used, time vs guide, recovery after challenge (yes/no), level reached (1–3), one practice tip for the diagnosed error.

### Nudges, help and escalation (committed; decision log 3, 3a)
Real quant interviews push back, give hints and get harder. Unbluffable does the same. Help is written for each candidate; what it costs is measured the same way for everyone.
- **First answer is the scored one.** A wrong or vague first answer is recorded as such: in a real interview that question is already lost.
- **Nudge rounds (after a wrong or vague answer):** the interviewer asks a question about the candidate's **own** reasoning, aimed at the step where it went wrong, e.g. *"You said 90%. Is that the chance a flag is fraud, or the chance fraud gets flagged?"*, *"Why would the base rate not matter here?"*, *"Are you sure the 5% applies to all transactions?"* The candidate answers; the interviewer nudges again as needed, up to **4 rounds**, until they reach the answer, ask to move on, or run out of rounds. Reported as "recovered after N nudges" or "not recovered".
- **Help on request:** "Can I get a hint?" / "Is it okay if I ask for help?" → *"Sure, what are you stuck on?"* → a hint written for what they said and where they are in the problem. No fixed number of hints; each one is counted.
- **Help offered:** no committed answer by 60% of the time guide → *"Is there anything you're stuck on?"* A "no" costs nothing.
- **Clarifying questions** ("are the two checks independent?") are answered from the template's fixed assumptions and never count as help.
- **How help is generated and kept honest:** every template has a fixed **solution map** (its steps in order; `02` §7). Muse Spark writes each nudge or hint for the candidate's own words and labels which step it targets. Code then (1) rejects any text containing the answer or a number that is neither a given nor a number the candidate has already said, and regenerates or falls back to a plain step prompt; (2) measures how far the help moved the candidate along the map. That distance, not the model's opinion, is what counts against them.
- **What counts against the candidate:** the help load (total steps given away) weakens the evidence from their next answer to that question (`02` §7). Time vs the guide (new puzzle 2 min, twin 1 min, follow-up 1.5 min) and the number of hints and nudges are shown on the end card; time does not change the label.
- **Escalation:** strong candidates get harder follow-ups on the same scenario: level 2 = a second, independent piece of evidence agrees; level 3 = it disagrees (`02` §7). "Level reached" is shown separately from the label.
- Positioning: an interviewer's nudges and hints with a cost, not tutoring; the full method is shown only on the end card.

### Interviewer voice (committed)
- The interviewer **speaks everything**: each question, each challenge, the follow-up, and the verdict. The same text appears on screen.
- Uses the browser's speech synthesis (Meta has no text-to-speech model; disclose this). Prefer the best natural-sounding English voice available (Chrome/Edge "Natural"/"Online" voices on Windows), with a fixed fallback order.
- **Hands-free conversation (decision log 4).** One "Start interview" tap (browsers require one gesture for mic and speech); after that the candidate never presses anything. The mic stays open; the interviewer speaks automatically.
- **Knowing when the candidate has finished:** after a short pause (~0.8 s) the app decides from *what* was said, not only silence: committed answer, question, help request or closer ("that's my answer") → respond now; mid-thought ("so the flagged ones are… um") → keep listening (thinking aloud is normal and never interrupted); ~8 s of silence → a gentle prompt (*"Want to talk me through where you are?"*). Cheap cues first; Muse Spark (`minimal`) only for unclear cases.
- **Barge-in:** with the "Using headphones" toggle on, the candidate can talk over the interviewer and it stops speaking. Without headphones, mic input is muted while the interviewer speaks (no echo).
- A small Done control remains as a fallback (noisy rooms, accessibility); never required. A visible "mute interviewer" toggle; text-only mode always works.
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
