"""Offline fakes for llm/ tests. Model responses here are synthetic fixtures,
not recordings of real calls."""

from __future__ import annotations

import json
from types import SimpleNamespace


def extraction(committed="none", quotes=(), code="vague", name="none", self_corrected=False):
    return {
        "committed_answer_text": committed,
        "reasoning_quotes": [{"quote": q, "step": s} for q, s in quotes],
        "reasoning_code": code,
        "misconception_name": name,
        "self_corrected": self_corrected,
    }


def chat_response(content, finish_reason="stop", refusal=None):
    if not isinstance(content, str):
        content = json.dumps(content)
    return {
        "id": "fake",
        "model": "muse-spark-1.3",
        "choices": [{
            "index": 0,
            "finish_reason": finish_reason,
            "message": {"role": "assistant", "content": content, "refusal": refusal},
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


class FakeClient:
    """Stands in for openai.OpenAI; records every create() call.

    `response` is returned for every call; pass a list to return them in turn
    (an Exception in the list is raised instead).
    """

    def __init__(self, response):
        self.calls = []
        self.response = response
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        body = self.response
        if isinstance(body, list):
            body = body[min(len(self.calls), len(body)) - 1]
        if isinstance(body, Exception):
            raise body
        return SimpleNamespace(model_dump=lambda: body)
