"""The in-app report for a finished Exam Room session (decision log 8).

Built only from what the session recorded: the candidate's own words, the
numbers they committed to, exact values from the engine, help counts and
times. The verdict label is the headline; no score or gauge. Internal
probabilities are model estimates (assumed likelihoods).
"""

from __future__ import annotations

from fractions import Fraction

from app import exam_text as say
from app import receipts
from app.interview_session import ExamSession, QuestionLog
from engine.bank import ForgePuzzle
from engine.labels import Label

LABEL_KEYS = {
    Label.SUPPORTS: "supports",
    Label.MISCONCEPTION: "misconception",
    Label.NOT_SHOWN: "not-shown",
    Label.MORE_EVIDENCE: "more-evidence",
}
MISCONCEPTIONS = {
    "transposed_conditional": ("Transposed conditional", "reading the chance of the evidence given the cause as the chance of the cause given the evidence."),
    "base_rate_neglect": ("Base rate neglect", "leaving out how rare the cause is to begin with."),
    "ignores_data": ("Ignores the evidence", "answering with the starting chance alone."),
    "ignores_prior": ("Ignores the starting chance", "using the evidence but dropping the prior."),
}
TIPS = {
    "transposed_conditional": "Before you answer, say which way the condition runs (\"given flagged, how likely fraud?\"). Then count both groups that show the evidence out of a round total.",
    "base_rate_neglect": "Start from a round total and the base rate, then count both groups that show the evidence before you divide.",
    "ignores_data": "After the starting chance, ask what the evidence changes: count both groups that show it.",
    "ignores_prior": "Keep the starting chance in: picture a round total and split it by the prior before applying the evidence.",
    None: "Say your plan out loud before the numbers: pick a round total, count both groups that show the evidence, then divide.",
}
FORGE_TIP = "Say your plan out loud before the numbers, work one step at a time, and check each step against the question."
LEVELS = 3


def pct(x: Fraction) -> str:
    return f"{float(x) * 100:.1f}%"


def exact_value(puzzle) -> str:
    """A forge answer as stored, with a decimal when it is not a whole number."""
    a = puzzle.answer
    return puzzle.answer_text + ("" if a.denominator == 1 or puzzle.answer_text == f"{float(a):g}" else f" ≈ {float(a):.4g}")


def exact(q: QuestionLog) -> str:
    if isinstance(q.puzzle, ForgePuzzle):
        return exact_value(q.puzzle)
    a, c = q.puzzle.answer, q.puzzle.counts
    keys = {"T1": ("fraud_flagged", "genuine_flagged"), "T2": ("defective_a", "defective_b"),
            "T3": ("biased_all_heads", "fair_all_heads")}[q.puzzle.template_id]
    hit, other = c[keys[0]], c[keys[1]]
    ratio = f"{hit}/{hit + other} = " if Fraction(hit, hit + other) == a and (hit, hit + other) != (a.numerator, a.denominator) else ""
    return f"{ratio}{a.numerator}/{a.denominator} ≈ {pct(a)}"


def misconception_name(key: str | None) -> str | None:
    return MISCONCEPTIONS[key][0] if key in MISCONCEPTIONS else key


def said(answer) -> str:
    if answer.span:
        return answer.span
    value = Fraction(answer.stated)
    return f"{value.numerator}/{value.denominator}"


def help_phrase(q: QuestionLog) -> str:
    parts = []
    if q.challenges:
        parts.append("the challenge")
    if q.nudges:
        parts.append(f"{q.nudges} nudge{'s' if q.nudges != 1 else ''}")
    if q.hints:
        parts.append(f"{q.hints} hint{'s' if q.hints != 1 else ''}")
    if not parts:
        return "no help"
    return ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]


def name(q: QuestionLog) -> str:
    return f"Question {q.number}" + (" (twin)" if q.kind == "twin" else "")


def outcome_text(q: QuestionLog) -> str:
    if q.scored is None:
        return "Not finished"
    if q.scored == "correct" and not q.recovered:
        return "Right, no help" if not (q.hints or q.nudges) else f"Right after {help_phrase(q)}"
    if q.scored == "correct":
        return f"Recovered after {help_phrase(q)}"
    return "Not recovered"


def number_item(q: QuestionLog, answer, title: str, text: str, exact_text: str | None = None) -> dict:
    item = {"title": title, "text": text, "quote": answer.transcript, "seen": [q.number], "receipt": answer.receipt}
    if answer.stated is not None:
        item["number"] = {"said": said(answer), "exact": exact_text or exact(q)}
    else:
        item["verdict"] = "No committed number"
    if answer.misconception:
        item["misconception"] = misconception_name(answer.misconception)
        item["text"] += f" Your number matches a known error: {item['misconception']}."
    return item


def part2_item(q: QuestionLog) -> dict | None:
    p = q.part2
    checked = [a for a in p.answers if a.outcome is not None] if p else []
    if not checked:
        return None
    answer = checked[-1]
    right = p.outcome == "correct"
    item = number_item(q, answer, "Part 2: right" if right else "Part 2: not the exact value",
                       "The follow-up after your correct answer. It is reported, not scored.",
                       exact_value(p.puzzle))
    item["question"] = p.text
    return item


def question_items(q: QuestionLog) -> list[dict]:
    checked = [a for a in q.answers if a.outcome is not None]
    if not checked:
        return []
    first, last = checked[0], checked[-1]
    items = []
    part2 = part2_item(q)
    if first.outcome == "correct":
        items.append(number_item(q, first, "Answer: right" + (" with no help" if not (q.hints or q.nudges) else ""),
                                 "You committed to the exact answer with your reasoning."))
        return items + ([part2] if part2 else [])
    first_title = {"named_wrong": "Opening answer: a named error", "other_wrong": "Opening answer: not the exact value",
                   "recited": "Opening answer: the previous puzzle's answer", "vague": "Opening answer: not committed or not explained"}
    items.append(number_item(q, first, first_title.get(first.outcome, "Opening answer"),
                             "This is the answer the interviewer challenged."))
    if q.help_lines:
        words = q.said[-1] if q.said else last.transcript
        items.append({"title": f"Help taken: {help_phrase(q)}",
                      "text": "What the interviewer said: " + " / ".join(t for _, t in q.help_lines),
                      "quote": words, "seen": [q.number], "verdict": outcome_text(q),
                      "receipt": score_receipt(q, words)})
    if last is not first:
        title = "Final answer: " + outcome_text(q).lower()
        items.append(number_item(q, last, title[0].upper() + title[1:], "Where you ended up on this question."))
    return items + ([part2] if part2 else [])


def score_receipt(q: QuestionLog, words: str) -> dict:
    return receipts.weight_receipt(words, q.help_load, bool(q.recovered), q.weight, q.scored)


def why_item(q: QuestionLog, questions: list[QuestionLog]) -> dict | None:
    """"Why these numbers?" for a diagnostic twin (decision log 16). Its receipt quotes
    the answer on the question before that showed the suspected error."""
    diagnostic = getattr(q.puzzle, "diagnostic", None)
    if diagnostic is None:
        return None
    words = None
    if diagnostic.suspected:
        earlier = [a for p in questions if p.number < q.number for a in p.answers
                   if a.misconception == diagnostic.misconception]
        words = earlier[-1].transcript if earlier else None
    item = {"title": "Why these numbers?", "text": say.why_numbers(diagnostic), "seen": [q.number],
            "why": {"misconception": diagnostic.misconception, "suspected": diagnostic.suspected,
                    "correct": say.value(diagnostic.correct), "wrong": say.value(diagnostic.wrong)},
            "receipt": receipts.why_receipt(diagnostic, words, q.puzzle.recited)}
    if words:
        item["quote"] = words
    return item


def build(session: ExamSession) -> dict:
    iv = session.interview
    qs = [q for q in session.questions if q.scored is not None]
    label = iv.label
    misconception = iv.misconception if label is Label.MISCONCEPTION else None
    first_errors = [q.first_wrong[0].misconception for q in qs if q.first_wrong and q.first_wrong[0].misconception]
    tip_key = misconception or (first_errors[0] if first_errors else None)
    forge = any(isinstance(q.puzzle, ForgePuzzle) for q in session.questions)

    evidence, checks, hints, times, outcomes = [], [], [], [], []
    for q in qs:
        checked = [a for a in q.answers if a.outcome is not None]
        if checked:
            evidence.append({"quote": checked[0].transcript, "note": f"{name(q)}, opening answer" + (" (challenged)" if q.challenges else ""),
                             "receipt": checked[0].receipt})
            if len(checked) > 1:
                evidence.append({"quote": checked[-1].transcript, "note": f"{name(q)}, where you ended up: {outcome_text(q).lower()}",
                                 "receipt": checked[-1].receipt})
            committed = [a for a in checked if a.stated is not None]
            if committed:
                checks.append({"q": name(q), "said": ", then ".join(dict.fromkeys(said(a) for a in committed)), "exact": exact(q),
                               "receipt": committed[-1].receipt})
        hints += [{"text": t} for k, t in q.help_lines if k == "hint"]
        times.append({"q": name(q), "seconds": round(q.seconds or 0), "guide": q.guide_seconds})
        outcomes.append({"q": name(q), "text": outcome_text(q), "help": help_phrase(q), "help_load": q.help_load,
                         "receipt": score_receipt(q, checked[-1].transcript if checked else "")})

    well, improve = [], []
    for q in qs:
        items = question_items(q)
        if not items:
            continue
        if q.scored == "correct":
            well.append({**items[-1], "title": "Keep doing this: " + ("right with no help" if not (q.recovered or q.hints or q.nudges) else "you got there")})
        if q.first_wrong is not None:
            key = q.first_wrong[0].misconception
            title = {"transposed_conditional": "Say which way the condition runs before you give a number",
                     "base_rate_neglect": "Start from the base rate and count both groups"}.get(
                key, "Show the steps behind your number" if forge else "Show the counts behind your number")
            improve.append({**items[0], "title": title})
        if q.hints:
            improve.append({"title": "Try the next step yourself before asking for help" if forge
                            else "Pick a round total yourself before asking for help",
                            "text": "You asked for a hint on this question.", "quote": q.said[0] if q.said else items[0]["quote"],
                            "seen": [q.number], "verdict": f"{q.hints} hint{'s' if q.hints != 1 else ''} used",
                            "receipt": score_receipt(q, q.said[0] if q.said else items[0]["quote"])})

    n = len(qs)
    overall = f"{n} question{'s' if n != 1 else ''}, scored on where you ended up, discounted by the help it took. " + " ".join(
        f"{name(q)}: {outcome_text(q).lower()}." for q in qs)
    if session.timed_out:
        overall += " The session ran out of time."

    estimate_names = (("S", "Sound (S)"), ("M", "Misconception (M)"), ("G", "Gap (G)"))
    return {
        "sample": False,
        "label": LABEL_KEYS[label],
        "misconception": misconception_name(misconception),
        "misconception_note": MISCONCEPTIONS[misconception][1] if misconception in MISCONCEPTIONS else None,
        "questions": n,
        "evidence": evidence,
        "checks": checks,
        "hints": hints,
        "challenges": sum(q.challenges for q in qs),
        "nudges": sum(q.nudges for q in qs),
        "outcomes": outcomes,
        "times": times,
        # Escalation levels 2-3 are not built yet, so every session ends at level 1.
        "level": 1,
        "levels": LEVELS,
        "tip": TIPS[tip_key] if tip_key in TIPS else FORGE_TIP if forge else TIPS[None],
        "estimate": [{"label": text, "p": f"{float(iv.posterior[key]):.3f}"} for key, text in estimate_names],
        "report": {
            "overall": overall,
            "well": well[:3],
            "improve": improve[:3],
            "breakdown": [{"tab": name(q), "sub": f"{'Twin, new numbers' if q.kind == 'twin' else 'New puzzle'} · "
                           + (f"{q.puzzle.topic}, {q.puzzle.difficulty} · " if isinstance(q.puzzle, ForgePuzzle) else "")
                           + f"{round(q.seconds or 0) // 60}:{round(q.seconds or 0) % 60:02d} against a "
                           f"{q.guide_seconds // 60}:{q.guide_seconds % 60:02d} guide · {help_phrase(q)}",
                           "items": question_items(q) + [w for w in [why_item(q, qs)] if w]} for q in qs],
        },
    }
