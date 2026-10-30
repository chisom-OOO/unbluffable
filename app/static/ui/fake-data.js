// The landing page's puzzle and its labelled sample exchange. Nothing here comes from a model or the engine.
// Two fair dice numbered 1 to 9 total 16 only as 7+9, 8+8 and 9+7; the first die is above seven
// in two of those three, so the exact answer is 2/3 (tests/test_landing_sample.py checks this).
window.UB_FAKE = {
  puzzle: {
    pack: "Quant",
    title: "Two dice, total sixteen",
    text: "I roll two fair dice numbered one to nine and tell you the total is sixteen. What's the chance the first die is above seven?",
    kind: "New puzzle",
  },

  // Landing sample (spec/01 "Landing"), labelled "Sample". `challenge` marks the words the
  // challenge quotes. Challenges are Socratic questions about the candidate's own words.
  replay: {
    lines: [
      { who: "candidate", text: "…so about a half, one half.", challenge: "a half" },
      { who: "interviewer", kind: "challenge", text: "You said a half. Which pairs actually give sixteen, and how many have the first die above seven?" },
      { who: "candidate", text: "Seven-nine, eight-eight, nine-seven. Two of three, so two thirds." },
    ],
  },
};
