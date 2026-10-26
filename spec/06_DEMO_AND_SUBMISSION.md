# 06 — Demo, submission and finals

## 2:00 video (every number from a saved run)
| Time | Show | Says |
| --- | --- | --- |
| 0:00–0:08 | You | [FIRSTHAND STORY, one sentence]. "Sounding right isn't the same as being right." |
| 0:08–1:05 | A live quant interview on your voice: the wrong posterior is challenged (mid-sentence if the gate passed), the follow-up, then the same puzzle with new numbers | "It checks the maths, not the confidence." |
| 1:05–1:20 | The evidence line | "Caught k/N; a careful chatbot caught j/N; fooled by k of N people." |
| 1:20–1:35 | A second puzzle by voice (or the software pack if built) | "Same engine, different checker." |
| 1:35–1:45 | Roadmap slide: software, cloud, medicine, Oxbridge; verified professionals | "Any high-stakes interview, once an expert checks the questions." |
| 1:45–2:00 | Meta stack (Spark, Voice Transcribe, Wonder) and the link | Name and tagline |
Record against warmed endpoints; trim waits with a visible "trimmed" tag; keep one unedited take as backup; label any replay footage.

## Gallery card
Cover frame: the challenge moment (transcript with the wrong posterior highlighted and the interviewer's line). First sentence carries one measured number.

## Submission description (draft — fill brackets)
> **Unbluffable — sounding right isn't the same as being right.** [Two-sentence firsthand story.]
> Practise probability interview puzzles out loud. Unbluffable transcribes your answer with Muse Voice Transcribe, reads your reasoning with Muse Spark, checks every number exactly, and challenges the wrong step [mid-sentence / as soon as you finish]. Then it asks the same puzzle with new numbers, to tell understanding from memorisation.
> **Measured:** caught [k/N] bluffs vs [j/N] for a carefully prompted chatbot (paired, McNemar); [k/N] false challenges on [N] tricky non-errors; fooled by [k] of [N] people; median challenge latency [x] s.
> **Meta models:** Muse Spark 1.3 (reasoning extraction, strict JSON), Muse Voice Transcribe (spoken answers), Muse Wonder (bluffs and red team). [Muse Code if used.]
> **Limits:** likelihoods are assumptions, not calibrated; a practice tool, not a hiring tool.
> **Disclosures:** [pre-kickoff planning documents; AI assistance as the rules require].

## README first screen
1. Name, tagline, 10-second GIF of the challenge moment.
2. Buttons: live link · video · results.
3. Four lines: problem (your story), what it does, how it differs, what each Meta model does.
4. Results table (the evidence line, with bounds and counts).
5. Run in 3 commands; replay mode works without a key.
6. Limits and disclosures.

## Finals (9 Nov)
- Versions: 90 s and 3 min. Second device and a phone hotspot ready.
- Run live; if any call takes more than 6 s, switch to replay, say so, keep talking.

## Q&A to rehearse
- **Why not just a calculator?** The calculator is half of it; the model reads spoken reasoning and quotes it, and the engine decides what to ask next and when it has seen enough.
- **Could a careful prompt do this?** Show the careful-chatbot arm honestly.
- **Are the probabilities real?** They're model estimates under stated likelihood assumptions, not calibrated — that's why the labels are words.
- **What if it interrupts wrongly?** Show the false-challenge result and the claim rules.
- **What did Meta's models do?** Name the three calls and the cost per session.
