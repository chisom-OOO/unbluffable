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
WORKER = (UI / "natural-voice-worker.js").read_text(encoding="utf-8")
INTERVIEW = (UI / "interview.js").read_text(encoding="utf-8")
PAGE = (ROOT / "app" / "templates" / "interview.html").read_text(encoding="utf-8")
BUNDLE_SHA384 = "suR1TeKe6Fe8fT0n/uTWoohnPJrp1zu3z0bj4VH2anmmq739wlmFSnMFJyMYszAC"


def test_switch_sits_under_interviewer_voice_and_is_off_by_default():
    # Hidden until WebGPU is confirmed (decision log 44): browsers without it never see it.
    assert '<label class="checkline natural-switch" id="natural-row" hidden>' in PAGE
    switch = re.search(r'<input type="checkbox" id="natural-voice"[^>]*>', PAGE)
    assert switch and 'role="switch"' in switch[0] and "checked" not in switch[0]
    assert "<span>Natural voice (beta)</span>" in PAGE
    assert PAGE.index("<summary>Interviewer voice</summary>") < PAGE.index('id="natural-voice"') < PAGE.index('id="voice-tip"')
    assert '<p class="fine natural-note" id="natural-note" hidden aria-live="polite"></p>' in PAGE
    assert PAGE.index('src="/ui-static/natural-voice.js"') < PAGE.index('src="/ui-static/interview.js"')


def test_the_switch_is_hidden_for_everyone_until_the_glitching_is_fixed():
    # Decision log 46: garbled audio in a live test (Opera, Windows). The code stays; it is not offered.
    assert "const OFFERED = false;" in NATURAL
    glue = NATURAL[NATURAL.index("// ---------- The browser"):]
    assert "controller.setAvailable(false)" in glue  # the row is hidden and a remembered "on" does nothing
    assert glue.index("if (!OFFERED)") < glue.index("requestAdapter")  # no WebGPU probe, no download


def test_switch_shows_only_when_webgpu_is_confirmed():
    wiring = INTERVIEW[INTERVIEW.index("the natural voice switch"):INTERVIEW.index('$("voice-select").addEventListener')]
    assert 'kind === "unavailable"' in wiring and '$("natural-row").hidden = true' in wiring
    assert '$("natural-row").hidden = !window.UBNatural.available()' in wiring
    glue = NATURAL[NATURAL.index("// ---------- The browser"):]
    assert "navigator.gpu" in glue and "requestAdapter" in glue and "controller.setAvailable(" in glue


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
    for source in (NATURAL, WORKER):
        hosts = set(re.findall(r"https://([a-z0-9.-]+)/", source))
        assert hosts <= {"cdn.jsdelivr.net", "huggingface.co"}, hosts
        assert "/api/" not in source and "WebSocket" not in source and "method:" not in source


def test_the_bundle_is_hash_checked_before_it_runs_in_a_worker():
    assert BUNDLE_SHA384 in NATURAL  # the pins travel to the worker
    assert 'crypto.subtle.digest("SHA-384"' in WORKER and 'crypto.subtle.digest("SHA-256"' in WORKER
    assert WORKER.index('digest("SHA-384"') < WORKER.index("await import(")
    assert "dtype: pin.dtype, device: pin.device" in WORKER and "fp32" not in WORKER + NATURAL.replace("never the 326 MB fp32", "")
    # Decision log 44: fp16 on WebGPU only; no WASM or 8-bit path ships.
    assert 'dtype: "fp16"' in NATURAL and 'device: "webgpu"' in NATURAL
    for source in (NATURAL, WORKER):
        assert '"wasm"' not in source and '"q8"' not in source and "model_quantized" not in source
    # Kokoro never runs on the page's main thread: WASM synthesis would freeze the interview.
    assert "import(" not in NATURAL and 'new Worker(WORKER, { type: "module" })' in NATURAL


def test_no_model_weights_are_committed():
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    assert not [p for p in tracked if p.endswith((".onnx", ".bin", ".safetensors"))]


def test_privacy_page_names_hugging_face_and_keeps_speech_text_local():
    html = TestClient(app).get("/ui/privacy").text
    assert "Hugging Face" in html and "browsers with WebGPU" in html
    assert "never leaves your browser" in html


def test_security_headers_are_unchanged():
    response = TestClient(app).get("/ui/interview")
    assert response.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert response.headers["x-frame-options"] == "DENY"
