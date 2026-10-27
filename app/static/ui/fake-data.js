// Fake data for the UI preview screens. Nothing here comes from a model or the engine.
// Numbers are consistent with the puzzle: 20 fraud, 18 flagged; 1,980 genuine, 99 flagged; 18/117 = 2/13.
window.UB_FAKE = {
  puzzle: {
    pack: "Quant",
    title: "The flagged transaction",
    text: "Out of 2,000 transactions, 1% are fraudulent. The detector flags 90% of fraudulent transactions and 5% of genuine ones. A transaction is flagged. What is the probability it is fraud?",
    guideSeconds: 120,
    kind: "New puzzle",
  },

  // Landing replay (spec/01 "Landing"). Labelled as a recorded run.
  replay: {
    recordedOn: "2026-10-21",
    lines: [
      { who: "candidate", text: "…so if a transaction gets flagged, it's about 90 percent likely to be fraud.", challenge: "90 percent" },
      { who: "interviewer", kind: "challenge", text: "Careful. 90% is the chance a fraudulent transaction gets flagged, not the chance a flagged transaction is fraud. Out of 2,000 transactions, how many genuine ones get flagged too?" },
    ],
  },

  // Interview script. Each candidate turn is "spoken" into the live transcript, then the interviewer answers.
  // `challenge` is the exact substring the interviewer challenged; it is highlighted in the transcript.
  script: [
    {
      candidate: "The detector catches 90% of fraud and flags 5% of genuine ones. So if a transaction gets flagged, it's about 90 percent likely to be fraud.",
      challenge: "90 percent",
      reply: { kind: "nudge", text: "You said 90 percent. Is that the chance a flag is fraud, or the chance fraud gets flagged?" },
    },
    {
      candidate: "Hmm. The chance fraud gets flagged, I think. So I need the other direction, but I'm not sure how to count the genuine ones.",
      reply: { kind: "nudge", text: "Good. What would you need to know about the genuine transactions to get the other direction?" },
    },
    {
      candidate: "So 20 are fraud and 18 of those get flagged. 1,980 are genuine and 99 get flagged. That's 18 out of 117, about 15 percent.",
      reply: { kind: "close", text: "That's right: 18 out of 117. Let's stop there." },
    },
  ],

  stuck: {
    ask: "Sure, what are you stuck on?",
    candidate: "I don't know where to start with the genuine ones.",
    hint: "Picture all 2,000 transactions. How many of them are genuine?",
  },

  offerHelp: "Is there anything you're stuck on?",

  models: [
    { model: "muse-spark-1.3", job: "Pull out the committed number", ms: 842, cost: "$0.0004" },
    { model: "engine (code)", job: "Exact check: 2/13, not 9/10", ms: 2, cost: "$0" },
    { model: "muse-spark-1.3", job: "Write the nudge for your words", ms: 1130, cost: "$0.0006" },
    { model: "engine (code)", job: "Reject answer leaks; pick next question", ms: 3, cost: "$0" },
    { model: "browser speech", job: "Interviewer voice", ms: 40, cost: "$0" },
  ],

  end: {
    label: "misconception",
    misconception: "Transposed conditional",
    evidence: [
      { quote: "So if a transaction gets flagged, it's about 90 percent likely to be fraud.", challenge: "90 percent", note: "Scored answer, question 1" },
      { quote: "That's 18 out of 117, about 15 percent.", note: "After 2 nudges and 1 hint" },
    ],
    check: { said: "90%", exact: "18/117 = 2/13 ≈ 15.4%" },
    hints: [
      { kind: "hint", text: "Picture all 2,000 transactions. How many of them are genuine?" },
    ],
    nudges: 2,
    recovered: true,
    time: { seconds: 161, guide: 120 },
    level: 1,
    levels: 3,
    questions: 2,
    tip: "Before you answer, say which way the condition runs: \"given flagged, how likely fraud?\" Then count both groups that get flagged out of a round total, like 2,000.",
    estimate: [
      { label: "Transposed conditional", p: "0.71" },
      { label: "Understands the base rate", p: "0.18" },
      { label: "Other error", p: "0.11" },
    ],
  },
};
