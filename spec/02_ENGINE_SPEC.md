# 02 — Engine spec (maths)

All figures below were checked with exact fractions. Likelihoods are **assumptions** (illustrative, versioned), not calibrated probabilities. Keep them in `content/likelihoods.yaml` with a version number.

## 1. Puzzle templates (fresh numbers each session)

### T1 — Fraud alert (flagship)
Parameters: base rate p (share of transactions that are fraudulent), detection rate s (share of fraud the detector flags), false-alarm rate f (share of genuine transactions flagged).
Answer: P(fraud | flagged) = p·s / (p·s + (1−p)·f).
Flagship: p = 1%, s = 90%, f = 5%. Out of 2,000 transactions: 20 fraudulent, 18 flagged; 1,980 genuine, 99 flagged → 18/117 = **2/13 ≈ 15.38%**.
(Framed as fraud, not a medical test, to stay clear of the hackathon's "AI medical advice" anti-project list; the maths is the classic medical-test problem.)
Named wrong values (all → Misconception): s = 90% (transposed conditional: "90% of fraud is flagged" read as "90% of flags are fraud"), 1 − f = 95%, f = 5% and P(+) = 5.85% (base rate / denominator errors; near-identical, reported together).
Flagship twin: p = 2% → 36/134 = **18/67 ≈ 26.87%**; P(+) = 6.7%.
Note: the detector's overall accuracy at the flagship numbers is 94.95% — never call 90% "accuracy"; it is the detection rate.

### T2 — Two machines
Machine A makes fraction a of items with defect rate dA; B makes 1 − a with rate dB. Given an item is defective, P(A | defect) = a·dA / (a·dA + (1−a)·dB).
Named wrong values: dA/(dA + dB) (ignores production shares), a (base rate only), dA (transposed).

### T3 — Two coins
A bag holds a biased coin (P(H) = b) with probability q and a fair coin otherwise. One coin is drawn and flipped k times; all heads. P(biased | k heads) = q·b^k / (q·b^k + (1−q)·0.5^k).
Named wrong values: q (ignores the flips), b^k / (b^k + 0.5^k) (ignores the prior), b^k (likelihood, not posterior).

### Generator rules (all templates)
- Natural-frequency counts must be whole numbers for the chosen population size (e.g. "out of 2,000").
- Reject any draw where the answer is within **2 percentage points** of any named wrong value.
- The twin keeps the template, changes one parameter, and must move the answer by **≥ 10 percentage points**; run the collision filter on the twin too, including the original answer (added as "Recited").
- Demo uses a fixed, labelled seed; practice and "try to fool it" use fresh numbers.
- Answer tolerance: exact fraction match, or within ±1 percentage point when stated as a percentage or decimal.

## 2. Observation coding (per answer)
Inputs: deterministic number check + Muse Spark extraction (`03` schema).
- **Correct:** number correct AND reasoning code is valid reasoning.
- **Named wrong:** number matches a named wrong value.
- **Other wrong:** number wrong, not a named value.
- **Vague:** no committed number, or correct number with unsupported/vague reasoning.
- **Recited** (twin only): the twin answer equals the original puzzle's answer.
- **System abstain** (no update): empty or unintelligible audio, transcription failure, injection-only text, off-topic.
Rule: a wrong number can never be coded Correct.

## 3. State and likelihoods
Per skill: probability over **Sound (S), Misconception (M), Gap (G)**; prior **0.4 / 0.3 / 0.3**.

### First answer: P(outcome | class)
| Outcome | S | M | G |
| --- | --- | --- | --- |
| Correct | 0.85 | 0.15 | 0.20 |
| Named wrong | 0.03 | 0.70 | 0.20 |
| Other wrong | 0.04 | 0.05 | 0.30 |
| Vague | 0.08 | 0.10 | 0.30 |

### Twin: P(twin outcome | class, first outcome) — not independent of the first answer
Cells read S / M / G. Every row sums to 1 per class.
| First → twin | Correct | Recited | Named wrong | Other wrong | Vague |
| --- | --- | --- | --- | --- | --- |
| After correct | .90/.20/.15 | .01/.50/.55 | .02/.15/.10 | .03/.10/.10 | .04/.05/.10 |
| After named wrong | .70/.10/.15 | — | .05/.75/.25 | .15/.10/.35 | .10/.05/.25 |
| After other wrong | .60/.15/.20 | — | .05/.50/.20 | .25/.25/.40 | .10/.10/.20 |
| After vague | .70/.15/.15 | — | .05/.55/.20 | .10/.15/.30 | .15/.15/.35 |

Same tables for all three templates (an assumption to revisit with data). A new puzzle after the twin uses the first-answer table again.

## 4. Question selection
Candidates at each step: the current puzzle's twin (if not yet asked) or a new puzzle from an unused template. Pick the maximum **expected information gain per minute** (entropy in bits; new puzzle = 2 min, twin = 1 min). Ties: fixed order (twin, T1, T2, T3).

Checked values (from the prior):
| After first answer | Twin (bits/min) | New puzzle (bits/min) | Engine asks |
| --- | --- | --- | --- |
| Correct | 0.389 | 0.170 | Twin |
| Named wrong | 0.207 | 0.110 | Twin |
| Vague | 0.242 | 0.185 | Twin |
| Other wrong | 0.104 | 0.129 | New puzzle |
At the prior, a new puzzle carries 0.249 bits/min.

## 5. Labels and stopping
Applied after **≥ 2 answers**, in order:
1. S ≥ 0.80 → Evidence supports understanding
2. M ≥ 0.70 → Misconception detected (name it)
3. S ≤ 0.10 → Understanding not shown
4. otherwise → More evidence needed
Stop at the first label other than "More evidence needed", or after 4 questions.

## 6. Pinned unit tests (expected posteriors, tolerance ±0.002)
| Sequence | S | M | G | Label |
| --- | --- | --- | --- | --- |
| Correct → twin correct | 0.944 | 0.028 | 0.028 | Evidence supports understanding |
| Correct → twin recited | 0.058 | 0.382 | 0.560 | Understanding not shown |
| Named wrong (one answer) | 0.043 | 0.745 | 0.213 | (none yet; ≥2 answers) |
| Named wrong → twin named wrong | 0.003 | 0.910 | 0.087 | Misconception detected |
| Vague (one answer) | 0.211 | 0.197 | 0.592 | (none yet) |
| Correct (one answer) | 0.764 | 0.101 | 0.135 | (none yet) |
Also test: selection table in §4; generator collision filter; tolerance rules; "the detector catches 90% of fraud" (a restated given) is not coded as an answer; flagship and twin answers (2/13, 18/67).

## 7. Hints, nudges and escalation (decision log 3)
### Hint discount
Hints weaken the evidence from the **next answer** to the same question. Mix that answer's likelihood row with an uninformative constant:
L'(o | c) = w · L(o | c) + (1 − w) · ¼, with **w = 1** (no hint), **¾** (H1), **½** (H2), **¼** (H3); with several hints, use the highest level given.
Applies to Correct only (a wrong answer after a hint is still wrong evidence). Exact fractions. With w = 1 every existing table and pinned test is unchanged.
Pinned (prior, one Correct answer): w = ¾ → S 0.707, M 0.132, G 0.161; w = ½ → S 0.633, M 0.173, G 0.194; w = ¼ → S 0.536, M 0.226, G 0.238.

### Nudges
After a challenge the candidate may re-answer once. The re-answer is recorded ("recovered after challenge": yes if Correct) but the posterior uses the first answer only (no double counting).

### Escalation (sequential evidence, all templates)
Trigger: label "Evidence supports understanding" reached with hint level ≤ H1. Ask up to two follow-ups on the same scenario, using the current puzzle's answer q as the new prior. Escalation answers set "level reached" (1 → 2 → 3) and do not change the posterior or label.
- **Level 2 — agreeing evidence:** T1: a second, independent check with the same rates also flags → q·s / (q·s + (1−q)·f). T2: a second item from the same machine is also defective → q·dA / (q·dA + (1−q)·dB). T3: one more flip, heads → q·b / (q·b + (1−q)·½).
- **Level 3 — conflicting evidence:** T1: the second check does **not** flag → q·(1−s) / (q·(1−s) + (1−q)·(1−f)). T2: the second item is fine → q·(1−dA) / (q·(1−dA) + (1−q)·(1−dB)). T3: the next flip is tails → q·(1−b) / (q·(1−b) + ½·(1−q)).
- Named wrong values: q (ignores the new evidence), the new evidence's rate alone (s, 1−s, dA, b, …), s² or its analogue (multiplies rates, ignores the prior); collision filter and tolerance as in §1. Reject a draw whose follow-up answers collide.
- Flagship pinned: L2 = **36/47 ≈ 76.6%** (named: 2/13, 81%, 90%); L3 = **4/213 ≈ 1.88%** (named: 2/13, 10%, 5%). Flagship twin (p = 2%): L2 ≈ 86.9%, L3 ≈ 3.72%.
- Interview length: at most 4 scored questions + 2 follow-ups.

