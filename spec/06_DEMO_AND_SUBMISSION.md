# 06 — Demo, submission and finals

## Judging facts (kickoff, 26 Oct)
Rubric (stage 2 and finals, 0–10 per criterion): **Impact 30%** (real-world potential, who benefits, fit with the problem statement) · **Use of Meta AI tooling 25%** (creative use beyond a basic integration) · **Technical depth 20%** · **Demo 25%** (a working demo that holds up, and a video worth watching). Stage 1 is pass/fail on theme fit and use of Meta AI products. In the finals (top 5 per track, 9 Nov, 12:00 PM ET = 17:00 UK) judges watch the **3-minute video** live and rank. The video is scored at every stage.

## 3:00 video (primary; every number from a saved run)
| Time | Show | Says | Rubric |
| --- | --- | --- | --- |
| 0:00–0:15 | You | [FIRSTHAND STORY]. "Sounding right isn't the same as being right." Who it's for: anyone facing a high-stakes interview without a coach to push back on their reasoning. | Impact |
| 0:15–1:20 | A live spoken interview on your voice: the interviewer asks aloud, you commit a wrong answer, it challenges you (mid-sentence if the gate passed), the follow-up, then the same puzzle with new numbers | "It checks the maths, not the confidence." | Demo |
| 1:20–1:45 | Spot the bluff: two confident answers, same right number; new numbers expose the reciter; a plain chatbot's verdict alongside | "A chatbot grades the sound. This grades the reasoning." | Demo, Impact |
| 1:45–2:15 | How Meta's models do the work: Voice Transcribe live partials + claim-stability rules; Muse Spark extraction with quotes constrained to the candidate's own words; Muse Wonder as the red-team bluffer; the same interview running on open weights (Glimmer / Spark Open via a partner) | One line per model; show the model panel | Meta tooling |
| 2:15–2:40 | Evidence line, with counts and bounds; tester quote | "Caught k/N; a careful chatbot caught j/N; false challenges k/N; fooled by k of N people." | Technical depth |
| 2:40–3:00 | Vision: one engine for every high-stakes interview (software, medicine, PhD, Oxbridge), questions from verified professionals; link | Name and tagline | Impact |

Record against warmed endpoints; trim waits with a visible "trimmed" tag; keep one unedited take as backup; label any replay footage.

## Gallery card
Cover frame: the challenge moment (transcript with the wrong posterior highlighted and the interviewer's line). First sentence carries one measured number.

## Submission description (draft — fill brackets)
> **Unbluffable — sounding right isn't the same as being right.** [Two-sentence firsthand story.]
> Practise probability interview puzzles out loud. Unbluffable transcribes your answer with Muse Voice Transcribe, reads your reasoning with Muse Spark, checks every number exactly, and challenges the wrong step [mid-sentence / as soon as you finish]. Then it asks the same puzzle with new numbers, to tell understanding from memorisation.
> **Measured:** caught [k/N] bluffs vs [j/N] for a carefully prompted chatbot (paired, McNemar); [k/N] false challenges on [N] tricky non-errors; fooled by [k] of [N] people; median challenge latency [x] s.
> **Meta models:** Muse Spark 1.3 (reasoning extraction, strict JSON), Muse Voice Transcribe (spoken answers), Muse Wonder (bluffs and red team). [Muse Code if used.]
> **Limits:** likelihoods are assumptions, not calibrated; a practice tool, not a hiring tool.
> **Disclosures:** prior work = planning documents in `spec/` written before kickoff (no code); all code written from 26 Oct. AI-assisted with Claude Code, Codex and Muse Code; all code reviewed and tested by me.

## README first screen
1. Name, tagline, 10-second GIF of the challenge moment.
2. Buttons: live link · video · results.
3. Four lines: problem (your story), what it does, how it differs, what each Meta model does.
4. Results table (the evidence line, with bounds and counts).
5. Run in 3 commands; replay mode works without a key.
6. Limits and disclosures.

## Finals (9 Nov, 17:00 UK)
- Judges watch the submitted 3-minute video live and rank the top 5; the video must stand alone.
- Be online and reachable on Discord; keep the live link up (always-on instance) in case judges try it.

## Bonus prizes to enter
- **Best Build on Meta Open Weights ($10K):** flag it in the submission; document the open-weights run (`03`).
- **Most Viral ($20K):** post a 30–45 s cut of the challenge moment on X on submission day; submit the link in the form; engagement counted to 8 Nov 11:59 PM ET.
- **Community Vote ($10K):** share the gallery link with friends, societies and Discord after submission; one vote per verified account; winner 16 Nov.

## Q&A to rehearse
- **Why not just a calculator?** The calculator is half of it; the model reads spoken reasoning and quotes it, and the engine decides what to ask next and when it has seen enough.
- **Could a careful prompt do this?** Show the careful-chatbot arm honestly.
- **Are the probabilities real?** They're model estimates under stated likelihood assumptions, not calibrated — that's why the labels are words.
- **What if it interrupts wrongly?** Show the false-challenge result and the claim rules.
- **What did Meta's models do?** Name the three calls and the cost per session.
