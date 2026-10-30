// The landing page's puzzle and its labelled sample exchange. Nothing here comes from a model or the engine.
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
};
