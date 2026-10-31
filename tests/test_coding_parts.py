"""The coding interview's structure (decision log 29): 45 minutes, one to three problems, each a
progression: Part 1 (the family's tests), Part 2 ("make it fast": large inputs built the same
way in the forge and in the browser, with a time limit; "correct but too slow" apart from
"wrong"), and the bonus Part 3 only after Part 2 passed with 12+ minutes left. Another problem
starts only with 15+ minutes left. Fake model; the candidate's outputs are computed here."""

import asyncio
import copy
import json
from fractions import Fraction
from pathlib import Path

import pytest

from app import coding
from forge import coding_scale, scale_gen

FIXTURE = Path(__file__).with_name("fixtures") / "coding"
SPEC = json.loads((FIXTURE / "sw_F001.json").read_text(encoding="utf-8"))


def best_run(gains):  # a right answer, in the test
    best = cur = gains[0]
    for g in gains[1:]:
        cur = max(g, cur + g)
        best = max(best, cur)
    return best


def positives(gains):  # the "ignores contiguity" mistake
    pos = [g for g in gains if g > 0]
    return sum(pos) if pos else max(gains)


CONFIG = coding_scale.infer(SPEC)
SCALE = {"template_id": SPEC["template_id"], "eligible": True, "n": 2000, "seeds": [11, 12, 13], "config": CONFIG,
         "expected": [str(best_run(scale_gen.generate(CONFIG, s, 2000)["values"])) for s in (11, 12, 13)],
         "solver_ms": [3.0, 3.1, 2.9], "time_limit_ms": 2000}
TWIST = {**copy.deepcopy(SPEC), "statement": "Now you may skip at most one day inside the run. Return the largest total.",
         "verification": {"verified": True, "variants": 50, "solver_reproduced": 50, "agreed_inputs": 300}}


def out(values):
    return [{"ok": True, "value": str(v)} for v in values]


def large(f, ms=5.0):
    return [{"ok": True, "value": str(f(scale_gen.generate(CONFIG, s, SCALE["n"])["values"])), "ms": ms} for s in SCALE["seeds"]]


def test_the_generator_is_shaped_like_the_tests_and_deterministic():
    assert CONFIG == {"params": [{"key": "values", "kind": "list", "lo": min(v for t in SPEC["tests"] for v in t[0]),
                                  "hi": max(v for t in SPEC["tests"] for v in t[0]), "sorted": False, "distinct": False,
                                  "same": None, "ge": None}]}
    a, b = scale_gen.generate(CONFIG, 5, 1000), scale_gen.generate(CONFIG, 5, 1000)
    assert a == b and len(a["values"]) == 1000 and scale_gen.generate(CONFIG, 6, 1000) != a


def test_inferred_relations_between_parameters():
    spec = {"parameters": [{"name": "starts", "type": "list[int]", "param": "s"}, {"name": "ends", "type": "list[int]", "param": "e"},
                           {"name": "slots", "type": "int", "param": "k"}, {"name": "flag", "type": "bool", "param": "f"}],
            "tests": [[[1, 5], [3, 9], 4, True], [[2, 2, 7], [2, 6, 8], 3, False]]}
    config = {p["key"]: p for p in coding_scale.infer(spec)["params"]}
    assert config["e"]["same"] == "s" and config["e"]["ge"] == {"of": "s", "lo": 0, "hi": 4}
    assert config["k"] == {"key": "k", "kind": "int", "len_plus": {"of": "s", "lo": 0, "hi": 2}}
    assert config["f"]["choices"] == [False, True]
    made = scale_gen.generate({"params": list(config.values())}, 1, 50)
    assert len(made["e"]) == len(made["s"]) == 50 and all(e >= s for s, e in zip(made["s"], made["e"])) and made["k"] >= 50
    assert coding_scale.infer({"parameters": [{"name": "words", "type": "list[str]", "param": "w"}], "tests": [[["a"]]]}) is None


def test_part_two_tells_right_but_slow_apart_from_wrong():
    right = coding.judge_scale(SPEC, SCALE, out(SPEC["expected"]), large(best_run))
    assert right["verdict"] == "fast" and right["large_correct"] == 3 and right["max_ms"] == 5
    slow = coding.judge_scale(SPEC, SCALE, out(SPEC["expected"]), large(best_run, ms=2500))
    assert slow["verdict"] == "slow" and slow["large_slow"] == 3
    stopped = coding.judge_scale(SPEC, SCALE, out(SPEC["expected"]), [{"ok": False, "timeout": True}] * 3)
    assert stopped["verdict"] == "stopped"
    wrong = coding.judge_scale(SPEC, SCALE, out(SPEC["expected"]), large(positives))
    assert wrong["verdict"] == "wrong" and wrong["large_correct"] < 3
    small_wrong = coding.judge_scale(SPEC, SCALE, out(SPEC["wrong_methods"][0]["outputs"]), large(best_run))
    assert small_wrong["verdict"] == "wrong" and small_wrong["named"] == "ignores contiguity"
    row = coding.receipt(SPEC, slow, "Muse Spark Open")["rows"][-1]
    assert row["key"] == "large" and row["text"] == "3/3 right at n = 2,000; slowest 2,500 ms (limit 2,000 ms per input)."
    # The page gets the generator and seeds, never the large expected outputs.
    public = coding.public_scale(SPEC, SCALE)
    assert public["generator"].startswith('"""Large inputs') and "expected" not in public and public["keys"] == ["values"]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Spark:
    async def structured(self, text, kind, effort, schema, prompt):
        return {"coding_plan": {"plan_quotes": [], "complexity_claim": "none"},
                "coding_question": {"question": "What does cur hold?"},
                "coding_follow_up": {"question": "What is the time complexity?", "focus": "complexity"},
                "coding_judge": {"verdict": "yes", "quote": "none"}}[kind], None


def interview(monkeypatch, tmp_path, script, minutes_per_step=1.0, twist=False, more=True):
    """Run a session from a script of client messages; each message advances the clock."""
    (tmp_path / "scale").mkdir(parents=True)
    (tmp_path / "scale" / "sw_F001.json").write_text(json.dumps(SCALE), encoding="utf-8")
    (tmp_path / "twist").mkdir()
    if twist:
        (tmp_path / "twist" / "sw_F001.json").write_text(json.dumps(TWIST), encoding="utf-8")
    monkeypatch.setenv("CODING_SCALE_DIR", str(tmp_path / "scale"))
    monkeypatch.setenv("CODING_TWIST_DIR", str(tmp_path / "twist"))
    coding._load_dir.cache_clear()
    clock, events, queue = Clock(), [], list(script)

    async def send(e):
        events.append(e)

    async def step():
        assert queue, f"the session wanted more: {[e for e in events if e['type'] == 'interviewer_line'][-1]['text']}"
        clock.t += minutes_per_step * 60
        return queue.pop(0)

    async def listen():
        return (await step())["text"]

    second = {**copy.deepcopy(SPEC), "template_id": "sw_F999"}
    session = coding.CodingSession(send, listen, step, Spark(), SPEC, deadline=coding.INTERVIEW_SECONDS, clock=clock,
                                   steps=["running_best", "max_consecutive_sum"], more=(lambda: (second, [])) if more else None)
    asyncio.run(session.run())
    assert not queue, f"unused: {queue}"
    return session, events


SAY = {"type": "speech", "text": "I keep a running total."}
RIGHT = {"type": "code_submit", "code": "def max_consecutive_gain(gains): ...", "outputs": out(SPEC["expected"])}
WRONG = {"type": "code_submit", "code": "...", "outputs": out(SPEC["wrong_methods"][0]["outputs"])}
FAST = {**RIGHT, "large": large(best_run)}
SLOW = {**RIGHT, "large": large(best_run, ms=2600)}


def lines(events, kind=None):
    return [e["text"] for e in events if e["type"] == "interviewer_line" and (kind is None or e["kind"] == kind)]


def test_part_two_follows_a_right_part_one_and_reports_slow_apart(monkeypatch, tmp_path):
    session, events = interview(monkeypatch, tmp_path, [SAY, RIGHT, SLOW, FAST, SAY], more=False)
    assert "Now n is up to 2,000; make it fast." in lines(events, "question")
    part = next(e for e in events if e["type"] == "coding_part")
    assert part["part"] == 2 and part["n"] == 2000 and "expected" not in part
    slow = [e for e in events if e["type"] == "coding_result" and e["part"] == 2][0]
    assert slow["verdict"] == "slow" and not slow["all_passed"]
    assert any("time complexity" in t and "2,000" in t for t in lines(events, "challenge"))
    report = coding.report(session)
    p = report["problems"][0]
    assert p["reached"] == "Part 2" and [x["label"] for x in p["parts"]] == ["Part 1", "Part 2"]
    assert [s["verdict"] for s in p["parts"][1]["submits"]] == ["slow", "fast"] and p["parts"][1]["verdict_text"] == "Correct and fast"
    items = report["rating_items"]
    assert [(i["difficulty"], i["outcome"]) for i in items] == [("Medium", "correct"), ("Hard", "correct")]
    assert items[1]["weight"] == "2/3"  # right only after a failing (slow) submit


def test_a_wrong_part_one_ends_the_problem_without_part_two(monkeypatch, tmp_path):
    session, events = interview(monkeypatch, tmp_path, [SAY, WRONG, WRONG, WRONG, SAY], more=False)
    assert not any(e["type"] == "coding_part" for e in events)
    assert coding.report(session)["problems"][0]["reached"] == "Part 1"


def test_a_next_problem_starts_only_with_fifteen_minutes_left(monkeypatch, tmp_path):
    # One minute per step: problem 1 (with Part 2) takes 4 minutes, so problem 2 starts with 41 left;
    # it has no Part 2 data, so it ends after Part 1 and a third starts with 38 left. Three is the most.
    script = [SAY, RIGHT, FAST, SAY] + [SAY, RIGHT, SAY] * 2
    session, events = interview(monkeypatch, tmp_path, script)
    assert [e["number"] for e in events if e["type"] == "question"] == [1, 2, 3]
    assert len(coding.report(session)["problems"]) == 3
    # Eight minutes per step: problem 1 uses 32 of 45 minutes; 13 are left, so no second problem.
    session, events = interview(monkeypatch, tmp_path / "slow", [SAY, RIGHT, FAST, SAY], minutes_per_step=8)
    assert [e["number"] for e in events if e["type"] == "question"] == [1]


def test_the_bonus_part_needs_part_two_passed_and_twelve_minutes(monkeypatch, tmp_path):
    hint = {"type": "speech", "text": "Can I get a hint?"}
    session, events = interview(monkeypatch, tmp_path, [SAY, RIGHT, FAST, hint, hint, RIGHT, SAY], twist=True, more=False)
    assert any(t.startswith(coding.PART3) and "skip at most one day" in t for t in lines(events, "question"))
    bonus = session.problems[0].parts[2]
    assert bonus.part == 3 and len(bonus.hints) == 2
    assert bonus.help_load == Fraction(1, 2) * (1 + 2)  # half the usual cost: steps 1 then 2 (H 1 + 2 at full cost)
    report = coding.report(session)
    assert report["problems"][0]["reached"] == "Part 3 (bonus)" and report["problems"][0]["parts"][2]["label"] == "Bonus part"
    assert report["rating_items"][-1]["bonus"] is True
    # Too little time: no bonus part.
    session, events = interview(monkeypatch, tmp_path / "late", [SAY, RIGHT, FAST, SAY], twist=True, more=False, minutes_per_step=12)  # Part 2 done at 36 minutes: 9 left
    assert not any(t.startswith(coding.PART3) for t in lines(events, "question"))


def test_a_wrong_bonus_part_never_lowers_the_rating(monkeypatch, tmp_path):
    session, _ = interview(monkeypatch, tmp_path, [SAY, RIGHT, FAST, WRONG, WRONG, WRONG, SAY], twist=True, more=False)
    items = coding.report(session)["rating_items"]
    assert [i["q"] for i in items] == ["Problem 1 · Part 1", "Problem 1 · Part 2"]  # no item for the wrong bonus part


def test_a_coding_interview_over_the_socket_reaches_part_two(monkeypatch, tmp_path):
    """The route: a 45-minute coding interview, Part 2 from the forge-made fixture
    (python -m forge.coding_scale --specs tests/fixtures/coding --out tests/fixtures/coding_scale)."""
    from fastapi.testclient import TestClient

    from app import interview_routes, voice_routes
    from app.main import app
    from test_bank_runtime import _packed_bank
    from test_coding import FakeSpark

    monkeypatch.setenv("CODING_DIR", str(FIXTURE))
    monkeypatch.setenv("CODING_SCALE_DIR", str(FIXTURE.with_name("coding_scale")))
    monkeypatch.setenv("CODING_TWIST_DIR", str(tmp_path / "none"))
    coding._load.cache_clear()
    coding._load_dir.cache_clear()
    monkeypatch.setattr(interview_routes, "_BANK", _packed_bank(("a", None, "Probability"), ("s", "software", "Dynamic programming")))
    monkeypatch.setattr(interview_routes, "_TOPICS", None)
    monkeypatch.setattr(voice_routes, "provider", lambda: FakeSpark())
    scale = json.loads((FIXTURE.with_name("coding_scale") / "sw_F001.json").read_text(encoding="utf-8"))

    def drain(socket, until):
        seen = []
        while True:
            seen.append(socket.receive_json())
            if seen[-1]["type"] in until:
                return seen

    with TestClient(app).websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True, "pack": "software", "typed_practice": True})
        seen = drain(socket, {"state"})
        assert next(e for e in seen if e["type"] == "session")["session_seconds"] == 45 * 60
        socket.send_json({"type": "typed", "transcript": "A running sum, reset when the next gain alone is bigger."})
        drain(socket, {"state"})
        socket.send_json({"type": "code_submit", "code": "...", "outputs": out(SPEC["expected"])})
        seen = drain(socket, {"state"})
        part = next(e for e in seen if e["type"] == "coding_part")
        assert (part["part"], part["n"], part["seeds"]) == (2, scale["n"], scale["seeds"]) and "expected" not in part
        made = [best_run(scale_gen.generate(part["config"], s, part["n"])["values"]) for s in part["seeds"]]
        assert [str(v) for v in made] == scale["expected"]  # the page's inputs match the forge's
        socket.send_json({"type": "code_submit", "code": "...", "outputs": out(SPEC["expected"]),
                          "large": [{"ok": True, "value": str(v), "ms": 40} for v in made]})
        seen = drain(socket, {"state"})
        result = next(e for e in seen if e["type"] == "coding_result")
        assert result["part"] == 2 and result["verdict"] == "fast" and result["all_passed"]
