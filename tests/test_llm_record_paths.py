"""Recordings hold answer text: the default record directory must be git-ignored.

Only replay/llm/demo/ is committed, deliberately.
"""

import shutil
import subprocess

import pytest

from eval.after_turn_set import DEFAULT_STORE
from llm.replay import DEFAULT_DIR, DEMO_DIR, ROOT, CallStore

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def ignored(path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    # --no-index: judge by .gitignore rules, even for paths that do not exist yet.
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", rel], cwd=ROOT, capture_output=True
    )
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


def test_default_record_directory_is_git_ignored(monkeypatch):
    monkeypatch.delenv("LLM_REPLAY_DIR", raising=False)
    assert CallStore().directory == DEFAULT_DIR
    assert ignored(DEFAULT_DIR / "0123abcd.json")


def test_eval_default_store_is_git_ignored():
    assert ignored(DEFAULT_STORE / "0123abcd.json")


def test_replay_llm_is_ignored_except_the_demo_folder():
    assert ignored(ROOT / "replay" / "llm" / "0123abcd.json")
    assert ignored(ROOT / "replay" / "llm" / "tester" / "0123abcd.json")
    assert not ignored(DEMO_DIR / "0123abcd.json")
