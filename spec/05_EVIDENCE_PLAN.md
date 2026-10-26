# 05 — Evidence plan

**Headline line (from first screen to video):** "Caught k/N bluffs · a careful chatbot caught j/N · fooled by k of N people." Fill only with measured numbers.

## Arms (same answers go to every arm)
1. **Plain chatbot:** Muse Spark, ordinary "give feedback" prompt.
2. **Careful chatbot:** Muse Spark told to be sceptical, check the numbers, and ask a same-puzzle-new-numbers follow-up; judgement by the model alone.
3. **Unbluffable:** exact checks + engine.
State each arm's tools explicitly.

## Wednesday early-warning check
10 bluffs + 10 real answers through the careful chatbot and Unbluffable. If the careful chatbot matches Unbluffable, change the headline (to transfer testing + live voice + exact verification) **before** building more. Log the decision.

## Saturday sets (generated after the prompt freeze; never used for tuning)
- Hard set: 10 right number + wrong reasoning; 10 right reasoning + arithmetic slip.
- 20 bluffs (Wonder drafts, hand-checked; labelled "model-written").
- 10 real correct answers.
- 60 tricky non-error utterances (restated givens, hypotheticals, self-corrections) + 40 real errors for the interruption test.

## Statistics
- Paired comparisons use the **exact McNemar test** on discordant pairs; show the pairs. Example: 20/20 vs 15/20 on the same items → one-sided p = 0.031, two-sided p = 0.0625 (not significant). Do not use Fisher's test for paired data.
- One-sided 95% upper bounds for zero-event results: 0/20 → ≤ 13.9%; 0/40 → ≤ 7.2%; 0/60 → ≤ 4.9%; 1/40 → ≤ 11.3%.
- Latency: median and maximum with counts (p95 from small samples is unstable).

## Optional: reasoning-effort comparison
Run the frozen hard set through Muse Spark at reasoning_effort low, medium and high. Report accuracy, median latency and cost per answer for each. Only if ahead by Friday.

## Human attackers
Invite people from quant and CS student communities (Thursday). Collect attempts with consent; store raw; rescore with the frozen prompt; "fooled" = credited "Evidence supports understanding" without valid reasoning, hand-labelled (state who labelled). Report "fooled by k of N". If fewer than 15 people take part, lead with the AI red team tally instead.

## Never claim
"Can't be fooled", calibrated, first, proves understanding, or interruption in packs that don't do it. Exact arithmetic validates an answer; the twin and reasoning check are the transfer test.
