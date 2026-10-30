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
from app.drill import DrillSession, drill_targets
from app.interview_session import ExamSession, QuestionLog
from engine.bank import ForgePuzzle, same_mistake
from engine.labels import Label

LABEL_KEYS = {
    Label.SUPPORTS: "supports",
    Label.MISCONCEPTION: "misconception",
    Label.NOT_SHOWN: "not-shown",
    Label.MORE_EVIDENCE: "more-evidence",
}
# One tip for every report: forge questions name their own misconceptions.
FORGE_TIP = "Say your plan out loud before the numbers, work one step at a time, and check each step against the question."
LEVELS = 3


def pct(x: Fraction) -> str:
    return f"{float(x) * 100:.1f}%"


def exact_value(puzzle) -> str:
    """A forge answer as stored, with a decimal when it is not a whole number."""
    a = puzzle.answer
    return puzzle.answer_text + ("" if a.denominator == 1 or puzzle.answer_text == f"{float(a):g}" else f" ≈ {float(a):.4g}")


def exact(q: QuestionLog) -> str:
    return exact_value(q.puzzle)


def misconception_name(key: str | None) -> str | None:
    return key  # forge misconceptions are named in the template


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
    if q.kind == "check":
        return "Check"
    if q.kind == "drill":
        return f"Drill {q.number}"
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


def follow_up_item(q: QuestionLog) -> dict | None:
    """The conceptual follow-up: model-matched, reported beside the exact checks, never scored."""
    f = q.follow_up
    if f is None or f.reply is None:
        return None
    return {"title": f"Follow-up: {f.label[len('Model-matched: '):]} (model-matched)",
            "text": "A question about the idea, after your correct answer. A model compared your reply with "
                    "the reference answer; it is not an exact check and is not scored.",
            "question": f.question, "quote": f.reply, "seen": [q.number], "verdict": f.label,
            "receipt": f.receipt}


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
                   if same_mistake(a.misconception, diagnostic.misconception)]
        words = earlier[-1].transcript if earlier else None
    item = {"title": "Why these numbers?", "text": say.why_numbers(diagnostic), "seen": [q.number],
            "why": {"misconception": diagnostic.misconception, "suspected": diagnostic.suspected,
                    "correct": say.value(diagnostic.correct), "wrong": say.value(diagnostic.wrong)},
            "receipt": receipts.why_receipt(diagnostic, words, q.puzzle.recited)}
    if words:
        item["quote"] = words
    return item


def card(q: QuestionLog, anchor: str) -> dict | None:
    """One evidence card per question: each of your answers quoted once, your committed
    number beside the exact value, the receipt, and any Part 2 or follow-up reply."""
    checked = [a for a in q.answers if a.outcome is not None]
    if not checked:
        return None
    words = [{"when": "Your answer" if len(checked) == 1 else "Opening answer", "text": checked[0].transcript}]
    if len(checked) > 1 and checked[-1].transcript != checked[0].transcript:
        words.append({"when": "Where you ended up", "text": checked[-1].transcript})
    committed = [a for a in checked if a.stated is not None]
    out = {"q": name(q), "anchor": anchor, "outcome": outcome_text(q), "words": words,
           "said": ", then ".join(dict.fromkeys(said(a) for a in committed)) if committed else None,
           "exact": exact(q), "receipt": (committed or checked)[-1].receipt, "part2": None, "follow_up": None}
    p = part2_item(q)
    if p:
        out["part2"] = {"question": p["question"], "words": p["quote"], "said": p.get("number", {}).get("said"),
                        "exact": p.get("number", {}).get("exact"), "title": p["title"], "receipt": p["receipt"]}
    f = q.follow_up
    if f is not None and f.reply is not None:
        out["follow_up"] = {"question": f.question, "words": f.reply, "verdict": f.label, "receipt": f.receipt}
    return out


def sections(qs: list[QuestionLog], forge: bool) -> dict:
    """Report lines for scored questions: quotes, checks, times, outcomes, what went well,
    what to improve and the per-question breakdown. Each line carries its receipt."""
    evidence, checks, hints, times, outcomes, follow_ups = [], [], [], [], [], []
    anchors = {id(q): f"card-{i + 1}" for i, q in enumerate(qs)}
    cards = [c for c in (card(q, anchors[id(q)]) for q in qs) if c]
    for q in qs:
        if q.follow_up is not None and q.follow_up.reply is not None:
            follow_ups.append({"q": name(q), "question": q.follow_up.question, "verdict": q.follow_up.label,
                               "quote": q.follow_up.quote, "receipt": q.follow_up.receipt})
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
        see = {"see": name(q), "anchor": anchors[id(q)]}
        if q.scored == "correct":
            well.append({**items[-1], **see, "title": "Keep doing this: " + ("right with no help" if not (q.recovered or q.hints or q.nudges) else "you got there")})
        if q.first_wrong is not None:
            improve.append({**items[0], **see, "title": "Show the steps behind your number"})
        if q.hints:
            improve.append({"title": "Try the next step yourself before asking for help",
                            "text": "You asked for a hint on this question.", "quote": q.said[0] if q.said else items[0]["quote"],
                            "seen": [q.number], **see, "verdict": f"{q.hints} hint{'s' if q.hints != 1 else ''} used",
                            "receipt": score_receipt(q, q.said[0] if q.said else items[0]["quote"])})

    kinds = {"twin": "Twin, new numbers", "drill": "Aimed at the mistake", "check": "New numbers, no help"}
    breakdown = [{"tab": name(q), "sub": f"{kinds.get(q.kind, 'New puzzle')} · "
                  + f"{q.puzzle.topic}, {q.puzzle.difficulty} · "
                  + f"{round(q.seconds or 0) // 60}:{round(q.seconds or 0) % 60:02d} against a "
                  f"{q.guide_seconds // 60}:{q.guide_seconds % 60:02d} guide · {help_phrase(q)}",
                  "items": question_items(q) + [w for w in [follow_up_item(q), why_item(q, qs)] if w]} for q in qs]
    return {"cards": cards, "evidence": evidence, "checks": checks, "follow_ups": follow_ups, "hints": hints, "times": times,
            "outcomes": outcomes,
            "well": well[:3], "improve": improve[:3], "breakdown": breakdown}


# Decision log 20: the report shows which mode was used.
CONDITIONS = {
    "exam": "Exam conditions: camera and microphone on",
    "typed": "Typed practice: not exam conditions",
    "replay": "Recorded replay: answers typed, model calls replayed",
}


def build(session: ExamSession, templates: dict | None = None) -> dict:
    iv = session.interview
    qs = [q for q in session.questions if q.scored is not None]
    label = iv.label
    misconception = iv.misconception if label is Label.MISCONCEPTION else None
    first_errors = [q.first_wrong[0].misconception for q in qs if q.first_wrong and q.first_wrong[0].misconception]
    tip_key = misconception or (first_errors[0] if first_errors else None)
    forge = any(isinstance(q.puzzle, ForgePuzzle) for q in session.questions)

    part = sections(qs, forge)

    n = len(qs)
    overall = f"{n} question{'s' if n != 1 else ''}, scored on where you ended up, discounted by the help it took. " + " ".join(
        f"{name(q)}: {outcome_text(q).lower()}." for q in qs)
    if session.timed_out:
        overall += " The session ran out of time."

    estimate_names = (("S", "Sound (S)"), ("M", "Misconception (M)"), ("G", "Gap (G)"))
    return {
        "sample": False,
        "conditions": CONDITIONS[session.conditions],
        "topics": session.topics,
        "label": LABEL_KEYS[label],
        "misconception": misconception_name(misconception),
        "misconception_note": None,
        "questions": n,
        "cards": part["cards"],
        "evidence": part["evidence"],
        "checks": part["checks"],
        "follow_ups": part["follow_ups"],
        "hints": part["hints"],
        "challenges": sum(q.challenges for q in qs),
        "nudges": sum(q.nudges for q in qs),
        "outcomes": part["outcomes"],
        "times": part["times"],
        # Escalation levels 2-3 are not built yet, so every session ends at level 1.
        "level": 1,
        "levels": LEVELS,
        "tip": FORGE_TIP,
        "estimate": [{"label": text, "p": f"{float(iv.posterior[key]):.3f}"} for key, text in estimate_names],
        "report": {"overall": overall, "well": part["well"], "improve": part["improve"], "breakdown": part["breakdown"]},
        # Drill mode (decision log 16): one "Drill this mistake" per detected misconception.
        "drills": [{"index": i, "misconception": t.misconception}
                   for i, t in enumerate(drill_targets(session, templates or {}))],
    }


def build_drill(session: DrillSession) -> dict:
    """The drill's report: "Cleared" or "Still showing" from the new-numbers check, then
    the same lines and receipts as an interview report. Not an interview label."""
    qs = [q for q in session.questions if q.scored is not None]
    if session.check is not None and session.check.scored is not None:
        qs.append(session.check)
    part = sections(qs, True)
    names = {q.number: name(q) for q in qs}
    for item in part["well"] + part["improve"] + [i for tab in part["breakdown"] for i in tab["items"]]:
        item["seen_names"] = [names[n] for n in item["seen"] if n in names]
    n = len(qs)
    overall = (f"{n} question{'s' if n != 1 else ''} aimed at one mistake. " + " ".join(
        f"{name(q)}: {outcome_text(q).lower()}." for q in qs))
    return {
        "sample": False,
        "conditions": CONDITIONS[session.conditions],
        "drill": {"misconception": session.target.misconception, "result": session.result,
                  "note": "From the final check, new numbers and no help: right with reasoning is Cleared."},
        "label": None,
        "misconception": None,
        "questions": n,
        "cards": part["cards"],
        "evidence": part["evidence"],
        "checks": part["checks"],
        "follow_ups": part["follow_ups"],
        "hints": part["hints"],
        "challenges": sum(q.challenges for q in qs),
        "nudges": sum(q.nudges for q in qs),
        "outcomes": part["outcomes"],
        "times": part["times"],
        "level": None,
        "levels": None,
        "tip": None,
        "estimate": [],
        "report": {"overall": overall, "well": part["well"], "improve": part["improve"], "breakdown": part["breakdown"]},
        "drills": [],
    }
