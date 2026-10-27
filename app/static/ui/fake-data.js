// Fake data for the UI preview screens. Nothing here comes from a model or the engine.
// The puzzle states percentages only (decision log 9); the hint introduces the round population of 2,000.
// Numbers are consistent with it: 20 fraud, 18 flagged; 1,980 genuine, 99 flagged; 18/117 = 2/13.
window.UB_FAKE = {
  puzzle: {
    pack: "Quant",
    title: "The flagged transaction",
    text: "1% of transactions are fraudulent. The detector flags 90% of fraudulent transactions and 5% of genuine ones. A transaction is flagged. What is the probability it is fraud?",
    guideSeconds: 120,
    kind: "New puzzle",
  },

  // Landing sample (spec/01 "Landing"). Written text, labelled as a sample until a real run is recorded.
  // Challenges are Socratic questions about the candidate's own words, never explanations.
  replay: {
    lines: [
      { who: "candidate", text: "…so if a transaction gets flagged, it's about 90 percent likely to be fraud.", challenge: "90 percent" },
      { who: "interviewer", kind: "challenge", text: "You said 90 percent. Is that the chance a flag is fraud, or the chance fraud gets flagged?" },
    ],
  },

  // Interview script. Each candidate turn is "spoken" into the live transcript, then the interviewer answers.
  // `challenge` is the exact substring the interviewer challenged; it is highlighted in the transcript.
  script: [
    {
      candidate: "The detector catches 90% of fraud and flags 5% of genuine ones. So if a transaction gets flagged, it's about 90 percent likely to be fraud.",
      challenge: "90 percent",
      reply: { kind: "challenge", text: "You said 90 percent. Is that the chance a flag is fraud, or the chance fraud gets flagged?" },
    },
    {
      candidate: "Hmm. The chance fraud gets flagged, I think. So I need the other direction, but I'm not sure how to count the genuine ones.",
      reply: { kind: "nudge", text: "Which transactions get flagged, apart from the fraudulent ones?" },
    },
    {
      candidate: "I don't know where to start with the genuine ones.",
      reply: { kind: "hint", text: "Imagine 2,000 transactions. How many of them would be genuine?" },
    },
    {
      candidate: "So 20 are fraud and 18 of those get flagged. 1,980 are genuine and 99 get flagged. That's 18 out of 117, about 15 percent.",
      reply: { kind: "close", text: "That's right: 18 out of 117. Now the same puzzle with new numbers." },
    },
  ],

  offerHelp: "Is there anything you're stuck on?",

  // Neutral acknowledgements, one before each interviewer reply (decision log 6). Fixed list, no model call.
  // Never anything that signals correctness before the check: no "Right", "Good", "Exactly", "Correct".
  acks: ["Got it.", "Understood.", "Okay.", "Thanks."],

  models: [
    { model: "muse-spark-1.3", job: "Pull out the committed number", ms: 842, cost: "$0.0004" },
    { model: "engine (code)", job: "Exact check: 2/13, not 9/10", ms: 2, cost: "$0" },
    { model: "muse-spark-1.3", job: "Write the nudge for your words", ms: 1130, cost: "$0.0006" },
    { model: "engine (code)", job: "Reject answer leaks; pick next question", ms: 3, cost: "$0" },
    { model: "browser speech", job: "Interviewer voice", ms: 40, cost: "$0" },
  ],

  // Sample end card (spec/02 §3, §5, §7), consistent with the script above plus a twin the preview doesn't play.
  // Q1 help load, solution map T1 (1 population, 2 fraud count, 3 flagged fraud, 4 flagged genuine, 5 total, 6 divide):
  //   challenge "Is that the chance a flag is fraud...?" points at no step: strength 0 (counted as the +1 below).
  //   candidate position stays 0 (the 90% and 5% are restated givens; turns 2 and 3 state no step value,
  //   and no population exists until the hint introduces one).
  //   nudge "Which transactions get flagged, apart from the fraudulent ones?" targets step 4: max(0, 4 - 0) = 4.
  //   hint "Imagine 2,000 transactions..." targets step 1 (pick a population): max(0, 1 - 0) = 1.  H = 5.
  // Q1 recovered: w = 2/(2 + 5 + 1) = 1/4; Correct row L' = w*L + (1-w)/4 = S 2/5, M 9/40, G 19/80.
  //   prior 4/10, 3/10, 3/10 -> unnormalised 4/25, 27/400, 57/800.
  // Q2 twin (p = 2%, 18/67), correct with no help: "after correct" row .90 / .20 / .15.
  //   -> S 256/299 = 0.856, M 24/299 = 0.080, G 19/299 = 0.064. Two answers, S >= 0.80: Evidence supports understanding.
  // Escalation needs H <= 1 on the scored answers; H = 5, so no follow-ups: level 1 of 3.
  end: {
    label: "supports",
    evidence: [
      { quote: "So if a transaction gets flagged, it's about 90 percent likely to be fraud.", challenge: "90 percent", note: "Opening answer, question 1 (challenged)" },
      { quote: "That's 18 out of 117, about 15 percent.", note: "Question 1, where you ended up: right, after the challenge, 1 nudge and 1 hint" },
      { quote: "40 are fraud and 36 get flagged; 1,960 genuine and 98 flagged. 36 out of 134, so 18 out of 67, about 27 percent.", note: "Question 2, same puzzle with new numbers (2% fraud): right, no help" },
    ],
    checks: [
      { q: "Question 1", said: "90%, then 18/117", exact: "18/117 = 2/13 ≈ 15.4%" },
      { q: "Question 2", said: "18/67", exact: "36/134 = 18/67 ≈ 26.9%" },
    ],
    hints: [
      { kind: "hint", text: "Imagine 2,000 transactions. How many of them would be genuine?" },
    ],
    challenges: 1,
    nudges: 1,
    recovered: true,
    // Guides per spec/01 and 02 §4: new puzzle 2 min, twin 1 min.
    times: [
      { q: "Question 1", seconds: 161, guide: 120 },
      { q: "Question 2 (twin)", seconds: 52, guide: 60 },
    ],
    level: 1,
    levels: 3,
    questions: 2,
    tip: "Before you answer, say which way the condition runs: \"given flagged, how likely fraud?\" Then count both groups that get flagged out of a round total, like 2,000.",
    estimate: [
      { label: "Sound (S)", p: "0.856" },
      { label: "Misconception (M)", p: "0.080" },
      { label: "Gap (G)", p: "0.064" },
    ],
  },
};
