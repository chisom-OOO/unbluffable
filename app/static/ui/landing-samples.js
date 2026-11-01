// The landing page's sample exchange, one per track. Each comes from a real forge family
// (content/forge/<family>.json, instance 1): the question and its spoken form are the family's
// own; the candidate commits to one of the family's verified wrong-method values; the
// challenge is a Socratic question about their own words that never gives the answer; the
// recovery reaches the family's stored answer. tests/test_landing_sample.py checks every number.
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
  },
  ib: {
    family: "ibx_F015",
    question: "Consider a retailer. Receivable days are 88, inventory days are 49, and payable days are 73. What is the cash conversion cycle, in days?",
    spoken: "Consider a retailer. Receivable days are eighty-eight, inventory days are forty-nine, and payable days are seventy-three. What is the cash conversion cycle, in days?",
    mistake: "adds_supplier_credit_days",
    lines: [
      { who: "candidate", text: "I'd add all three: 88, 49 and 73, so the cycle is 210 days.", challenge: "210 days", value: "210" },
      { who: "interviewer", kind: "challenge", text: "You said 210 days. Do payable days keep your cash tied up longer, or give it back sooner?" },
      { who: "candidate", text: "Sooner, so I subtract them. 88 plus 49 minus 73 is 64 days.", value: "64" },
    ],
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
  },
};
