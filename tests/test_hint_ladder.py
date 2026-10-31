"""The hint ladder (decision log 27): each nudge or hint goes one step further along the
family's solution steps, never repeating or paraphrasing an earlier line; H still grows."""

import json
from pathlib import Path

from app import exam_text as say
from app.hint_ladder import next_help, repeats
from app.interview_session import leak
from engine.bank import instance_puzzle, parse_template
from test_exam_session import lines, run_session

ROOT = Path(__file__).resolve().parents[1]


def test_two_hints_in_a_row_never_repeat_and_the_second_goes_to_a_later_step():
    session, events = run_session(["hint", "idk", "hint", "idk", "right", "right"])
    hints = lines(events, "hint")
    assert len(hints) == 2 and hints[0]["text"] != hints[1]["text"]
    assert not repeats(hints[1]["text"], [hints[0]["text"]])
    assert hints[1]["target_step"] > hints[0]["target_step"]
    q1 = session.questions[0]
    assert q1.help_load == hints[0]["target_step"] + hints[1]["target_step"]  # both from position 0


def test_nudges_after_the_challenge_climb_and_never_repeat_any_earlier_line():
    session, events = run_session(["other"] * 10)
    q1 = session.questions[0]
    said = [t for _, t in q1.help_lines]
    assert len(said) == 4  # the challenge and three nudges
    for i, text in enumerate(said[1:], 1):
        assert not repeats(text, said[:i]), text
    targets = [n["target_step"] for n in lines(events, "nudge")[:3]]
    assert targets == sorted(targets) and len(set(targets)) == min(3, len(q1.puzzle.steps))
    assert all(t.endswith("?") or t == say.FORGE_NUDGE for t in said)


def test_beta_prior_family_climbs_its_solution_steps():
    """Beta(5,4) prior, 10 of 16: stuck on the posterior alpha, the next hint is a later step."""
    raw = json.loads((ROOT / "content" / "forge" / "family_F048.json").read_text(encoding="utf-8"))
    template = parse_template(raw)
    puzzle = instance_puzzle(template, template.instances[0], 0)
    allowed = lambda t: leak(puzzle, t, [], None) is None  # noqa: E731
    first = next_help(puzzle, 0, None, [], allowed)
    assert first == (1, "What do you get for the alpha posterior?")
    second = next_help(puzzle, 0, first[0], [first[1]], allowed)
    assert second[0] == 2 and not repeats(second[1], [first[1]])
    assert "alpha posterior" in second[1] and "beta posterior" in second[1]
    # The posterior alpha (15) is not a given or said, so the hint names it without its value.
    assert "15" not in second[1]
    # Past the last step, help keeps changing.
    seen = [first[1], second[1]]
    target = second[0]
    for _ in range(4):
        target, text = next_help(puzzle, 0, target, seen, allowed)
        assert not repeats(text, seen[:5]) or len(seen) > 5
        seen.append(text)
    assert target == len(puzzle.steps)


def test_a_step_value_is_said_only_when_the_leak_guard_allows_it():
    raw = json.loads((ROOT / "content" / "forge" / "family_F048.json").read_text(encoding="utf-8"))
    template = parse_template(raw)
    puzzle = instance_puzzle(template, template.instances[0], 0)
    value = puzzle.steps[0].value
    said = [value]  # the candidate already said the posterior alpha
    allowed = lambda t: leak(puzzle, t, said, None) is None  # noqa: E731
    target, text = next_help(puzzle, 1, 1, ["What do you get for the alpha posterior?"], allowed)
    assert target == 2 and text.startswith(f"The alpha posterior is {value}.")
