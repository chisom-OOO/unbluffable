"""Decision log 43: the optional natural voice (beta). The behaviour is unit-tested in Node
(tests/natural_voice_unit.cjs); these check the page wiring, the pins and what may be loaded."""

import re
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "app" / "static" / "ui"
NATURAL = (UI / "natural-voice.js").read_text(encoding="utf-8")
INTERVIEW = (UI / "interview.js").read_text(encoding="utf-8")
PAGE = (ROOT / "app" / "templates" / "interview.html").read_text(encoding="utf-8")
BUNDLE_SHA384 = "suR1TeKe6Fe8fT0n/uTWoohnPJrp1zu3z0bj4VH2anmmq739wlmFSnMFJyMYszAC"


def test_switch_sits_under_interviewer_voice_and_is_off_by_default():
    switch = re.search(r'<input type="checkbox" id="natural-voice"[^>]*>', PAGE)
    assert switch and 'role="switch"' in switch[0] and "checked" not in switch[0]
    assert "<span>Natural voice (beta)</span>" in PAGE
    assert PAGE.index("<summary>Interviewer voice</summary>") < PAGE.index('id="natural-voice"') < PAGE.index('id="voice-tip"')
    assert '<p class="fine natural-note" id="natural-note" hidden aria-live="polite"></p>' in PAGE
    assert PAGE.index('src="/ui-static/natural-voice.js"') < PAGE.index('src="/ui-static/interview.js"')


def test_one_speaking_path_for_both_voices():
    speak = INTERVIEW[INTERVIEW.index("function speak(text"):INTERVIEW.index("function cancelSpeech")]
    # The natural line reports through the same start and end as an utterance: "Speaking",
    # the mic mute without headphones, and interviewer_speaking to the server (row 40).
    assert "natural.speakLine(" in speak and "onStart: started" in speak and "onStart: started," in speak
    assert speak.count("counted = true; speaking++; if (mutes) muting++;") == 1
    assert "natural.lineFailed()" in speak  # a failed line: the browser voice finishes it
    cancel = INTERVIEW[INTERVIEW.index("function cancelSpeech"):INTERVIEW.index("// ---------- Interviewer lines type out")]
    assert "g.cancel()" in cancel  # barge-in cancels a natural line like an utterance
    assert "natural.started()" in INTERVIEW[INTERVIEW.index("async function begin"):]


def test_only_jsdelivr_and_hugging_face_are_contacted_and_no_text_is_sent():
    hosts = set(re.findall(r"https://([a-z0-9.-]+)/", NATURAL))
    assert hosts == {"cdn.jsdelivr.net", "huggingface.co"}, hosts
    assert "/api/" not in NATURAL and "WebSocket" not in NATURAL and "method:" not in NATURAL


def test_the_bundle_is_hash_checked_before_it_runs():
    assert BUNDLE_SHA384 in NATURAL
    assert 'crypto.subtle.digest("SHA-384"' in NATURAL and 'crypto.subtle.digest("SHA-256"' in NATURAL
    assert NATURAL.index('digest("SHA-384"') < NATURAL.index("await import(")
    assert 'dtype: PIN.dtype' in NATURAL and '"fp32"' not in NATURAL


def test_no_model_weights_are_committed():
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    assert not [p for p in tracked if p.endswith((".onnx", ".bin", ".safetensors"))]


def test_privacy_page_names_hugging_face_and_keeps_speech_text_local():
    html = TestClient(app).get("/ui/privacy").text
    assert "Hugging Face" in html
    assert "never leaves your browser" in html


def test_security_headers_are_unchanged():
    response = TestClient(app).get("/ui/interview")
    assert response.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert response.headers["x-frame-options"] == "DENY"
