"""Behavioural end-of-answer (decision log 27): a long STAR story finishes on its own, never
with the committed-number silence prompt; unclear cases ask once whether there is more."""

import asyncio

from voice.endpointing import ANYTHING_TO_ADD, PROMPT, BehaviouralTurn
from voice.relay import wait_for_turn_policy
from voice.turns import AnswerMerger

# A long past-behaviour answer in the shape of the recorded test (no candidate data).
STAR = ("So in my second year I was on a team of four for a university case competition. "
        "Our task was to build a market entry plan for a mid-sized retailer in two weeks. "
        "Two people had exams so I took on structuring the work, I split the plan into market sizing, "
        "competitors and the financial case, and I set up a short call every evening to check progress. "
        "When our numbers didn't match I rebuilt the model with one of my teammates over a weekend. "
        "We presented to the judges on the final day and we ended up winning the competition.")


def test_a_star_story_ending_in_an_outcome_finishes_after_a_short_pause_without_prompting():
    turn = BehaviouralTurn()
    assert turn.decide(STAR, 0.5).action is None
    decision = turn.decide(STAR, 1.5)
    assert (decision.action, decision.cue) == ("finish", "wrap_up_cue")


def test_an_outcome_finishes_after_about_three_seconds_and_wrap_up_phrases_sooner():
    story = "I led the migration and as a result the team cut release time by thirty percent"
    turn = BehaviouralTurn()
    assert turn.decide(story, 2.9).action is None and turn.decide(story, 3.0).cue == "outcome_pause"
    for cue in ("so yeah", "and that's how we shipped it", "that's it"):
        assert BehaviouralTurn().decide(f"I talked to each of them separately. {cue}", 1.5).cue == "wrap_up_cue"


def test_forty_words_and_five_seconds_of_silence_finish_a_long_answer():
    long = " ".join(["I spoke to the manager about the deadline and the scope of the work"] * 4)
    turn = BehaviouralTurn()
    assert turn.decide(long, 4.9).action is None and turn.decide(long, 5.0).cue == "long_silence"


def test_unclear_answers_get_one_anything_to_add_then_finish_on_the_reply():
    short = "There was a disagreement about the approach"
    turn = BehaviouralTurn()
    assert turn.decide(short, 5).action is None
    assert turn.decide(short, 8).action == "ask"
    assert turn.decide(short, 9).action is None  # asked once only
    assert turn.decide(short + ". No, that covers it", 1.5).cue == "after_ask"
    other = BehaviouralTurn()
    other.decide(short, 8)
    assert other.decide(short, 16).cue == "silence_after_ask"


def test_a_trailing_clause_never_finishes_early():
    assert BehaviouralTurn().decide(STAR.rstrip(".") + " and", 5.5).action is None


def test_the_relay_finishes_the_star_story_and_never_sends_the_number_prompt():
    async def run():
        merger, sent, changed = AnswerMerger(0.8), [], asyncio.Event()

        class Browser:
            async def send_json(self, event):
                sent.append(event)
        loop = asyncio.get_running_loop()
        start = loop.time()
        merger.feed({"type": "speechStart", "turnId": 1}, 0)
        merger.feed({"type": "speechComplete", "turnId": 1, "transcript": STAR}, 0)
        policy = BehaviouralTurn(cue_pause=0.05, outcome_pause=0.1, long_pause=0.2, ask_pause=0.3)
        cue = await asyncio.wait_for(wait_for_turn_policy(merger, Browser(), changed, lambda: loop.time() - start, policy), 2)
        return cue, sent
    cue, sent = asyncio.run(run())
    assert cue == "wrap_up_cue"
    assert sent == [{"type": "endpoint_decision", "finished": True, "kind": "answer", "cue": "wrap_up_cue", "model": None}]
    assert not any(e.get("message") == PROMPT for e in sent)


def test_the_relay_asks_anything_to_add_once_for_an_unclear_answer():
    async def run():
        merger, sent, changed = AnswerMerger(0.8), [], asyncio.Event()

        class Browser:
            async def send_json(self, event):
                sent.append(event)
        loop = asyncio.get_running_loop()
        start = loop.time()
        merger.feed({"type": "speechStart", "turnId": 1}, 0)
        merger.feed({"type": "speechComplete", "turnId": 1, "transcript": "There was a disagreement"}, 0)
        policy = BehaviouralTurn(cue_pause=0.05, outcome_pause=0.1, long_pause=0.2, ask_pause=0.1)
        return await asyncio.wait_for(wait_for_turn_policy(merger, Browser(), changed, lambda: loop.time() - start, policy), 2), sent
    cue, sent = asyncio.run(run())
    assert [e["message"] for e in sent if e["type"] == "listening_prompt"] == [ANYTHING_TO_ADD]
    assert cue == "silence_after_ask"
