// Pure turn rules for the Exam Room, shared by the page and the Node unit test.
(() => {
  // Help offered at 60% of the guide (spec/01) only to a candidate who has been silent since the
  // question ended: never with a live transcript, typed text, or any speech heard this question.
  function shouldOfferHelp(s) {
    if (s.offered || s.answered || s.heard) return false;
    if (s.phase !== "listening" || s.speaking) return false;
    if ((s.liveText || "").trim() || (s.typedText || "").trim()) return false;
    return s.elapsed >= Math.round(s.guide * 0.6);
  }

  const api = { shouldOfferHelp };
  if (typeof module !== "undefined") module.exports = api;
  else window.UBTurn = api;
})();
