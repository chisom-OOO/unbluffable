// The landing page's sample exchange, one per track. Each comes from a real forge family
// (content/forge/<family>.json, instance 1): the question and its spoken form are the family's
// own; the candidate commits to one of the family's verified wrong-method values; the
// challenge is a Socratic question about their own words that never gives the answer; the
// recovery reaches the family's stored answer. Then the twin: the same family's instance that
// the engine picks for that mistake, and a one-line correct answer.
// tests/test_landing_sample.py checks every number.
// `challenge` marks the words the challenge quotes; `value` is the number a line commits to.
window.UB_SAMPLES = {
  quant: {
    family: "qx_F004",
    question: "5 identical machines make 150 parts in 6 hours at a constant rate. How many parts would 2 machines make in 8 hours?",
    spoken: "five identical machines make one hundred and fifty parts in six hours at a constant rate. How many parts would two machines make in eight hours?",
    mistake: "ignores_the_change_in_hours",
    lines: [
      { who: "candidate", text: "Two machines out of five is two fifths of 150, so I think it's 60 parts.", challenge: "60 parts", value: "60" },
      { who: "interviewer", kind: "challenge", text: "You said 60. How long do the two machines run, compared with the five?" },
      { who: "candidate", text: "Eight hours, not six. So 60 times 8 over 6, which is 80 parts.", value: "80" },
    ],
    // The twin: the engine's own choice for this mistake (instance 36).
    twin: {
      instance: 35,
      question: "3 identical machines make 60 parts in 2 hours at a constant rate. How many parts would 8 machines make in 10 hours?",
      spoken: "three identical machines make sixty parts in two hours at a constant rate. How many parts would eight machines make in ten hours?",
      answer: { text: "That's 10 parts per machine-hour, times 8 machines and 10 hours, so 800 parts.", value: "800" },
    },
  },
  ib: {
    family: "ibx_F015",
    question: "Consider a retailer. Receivable days are 88, inventory days are 49, and payable days are 73. What is the cash conversion cycle, in days?",
    spoken: "Consider a retailer. Receivable days are eighty-eight, inventory days are forty-nine, and payable days are seventy-three. What is the cash conversion cycle, in days?",
    mistake: "adds_supplier_credit_days",
    lines: [
      { who: "candidate", text: "I'd add all three: 88, 49 and 73, so the cycle is 210 days.", challenge: "210 days", value: "210" },
      { who: "interviewer", kind: "challenge", text: "You said 210 days. Does paying your suppliers later lengthen or shorten the time your cash is tied up?" },
      { who: "candidate", text: "Shorten, so I subtract them. 88 plus 49 minus 73 is 64 days.", value: "64" },
    ],
    // The twin: the engine's own choice for this mistake (instance 29).
    twin: {
      instance: 28,
      question: "Consider a publisher. Receivable days are 15, inventory days are 15, and payable days are 109. What is the cash conversion cycle, in days?",
      spoken: "Consider a publisher. Receivable days are fifteen, inventory days are fifteen, and payable days are one hundred and nine. What is the cash conversion cycle, in days?",
      answer: { text: "Add 15 and 15, take away 109, so it's minus 79 days.", value: "-79" },
    },
  },
  consulting: {
    family: "co_F025",
    question: "A campaign spends 600 thousand dollars and acquires 1,000 new customers. What is average acquisition cost, in dollars per new customer?",
    spoken: "A campaign spends six hundred thousand dollars and acquires one thousand new customers. What is average acquisition cost, in dollars per new customer?",
    mistake: "forget_thousands_multiplier",
    lines: [
      { who: "candidate", text: "It's 600 over 1,000, so I think it's 0.6 dollars per customer.", challenge: "0.6 dollars", value: "0.6" },
      { who: "interviewer", kind: "challenge", text: "You said 0.6 dollars. What unit is the campaign spend in?" },
      { who: "candidate", text: "Thousands of dollars. So it's 600 thousand over 1,000, which is 600 dollars per customer.", value: "600" },
    ],
    // The twin: the engine's own choice for this mistake (instance 9).
    twin: {
      instance: 8,
      question: "A campaign spends 700 thousand dollars and acquires 400 new customers. What is average acquisition cost, in dollars per new customer?",
      spoken: "A campaign spends seven hundred thousand dollars and acquires four hundred new customers. What is average acquisition cost, in dollars per new customer?",
      answer: { text: "It's 700 thousand over 400, so 1,750 dollars per customer.", value: "1750" },
    },
  },
  software: {
    family: "swf_F015",
    question: "In sorted values 3, 10, 12, 27, 34, 47, 54, find the first value strictly greater than 12. Return minus one if none qualifies. What integer should your function return?",
    spoken: "In sorted values three, ten, twelve, twenty-seven, thirty-four, forty-seven, fifty-four, find the first value strictly greater than twelve. Return minus one if none qualifies. What integer should your function return?",
    mistake: "uses_greater_or_equal_instead_of_strictly_greater",
    lines: [
      { who: "candidate", text: "I'd binary search for the first value at least 12, so it returns 12.", challenge: "returns 12", value: "12" },
      { who: "interviewer", kind: "challenge", text: "You said it returns 12. Read the condition again: what does strictly greater rule out?" },
      { who: "candidate", text: "It rules out 12 itself, so the search should return 27.", value: "27" },
    ],
    // The twin: the engine's own choice for this mistake (instance 27).
    twin: {
      instance: 26,
      question: "In sorted values 8, 9, 38, 40, 47, 49, 60, find the first value strictly greater than 9. Return minus one if none qualifies. What integer should your function return?",
      spoken: "In sorted values eight, nine, thirty-eight, forty, forty-seven, forty-nine, sixty, find the first value strictly greater than nine. Return minus one if none qualifies. What integer should your function return?",
      answer: { text: "Strictly greater than 9 skips the 9 itself, so it returns 38.", value: "38" },
    },
  },
};
