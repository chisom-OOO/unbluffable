"""Live bug (Opera, Windows): in a mixed quant interview (Probability, then Market making) the page
went blank at the switch to the market game. The room had scrolled the page down during the
questions; the market room is one screen tall and scrolls its own transcript, but the transcript's
hidden accessibility spans (position: absolute) escaped that scroll box, so the page stayed
thousands of pixels tall and the view was left below the room.

Reproduced in a real headless browser (Edge or Chrome; skipped when neither is installed) with a
recorded session from fake models, and pinned in the CSS and the room script."""

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

from app import mixed, voice_routes

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "app" / "static" / "ui" / "exam-room.css").read_text(encoding="utf-8")
JS = (ROOT / "app" / "static" / "ui" / "interview.js").read_text(encoding="utf-8")
BROWSERS = [os.environ.get("BROWSER_EXE", ""),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/microsoft-edge"]


def test_the_market_transcript_contains_its_hidden_spans():
    # The scroll box is the containing block of its absolutely positioned (visually hidden) spans.
    rule = CSS[CSS.index(".room.market #log {"):]
    rule = rule[:rule.index("}")]
    assert "overflow-y: auto" in rule and "position: relative" in rule


def test_entering_the_market_room_starts_the_page_at_the_top():
    question = JS[JS.index('case "question":'):JS.index('case "scored":')]
    assert "const enteringMarket = event.kind === \"market\" && !marketRoom();" in question
    toggle = question.index('$("room").classList.toggle("market", event.kind === "market");')
    reset = question.index("if (enteringMarket) {")
    assert toggle < reset
    assert "window.scrollTo(0, 0);" in question[reset:] and "log.scrollTop = log.scrollHeight;" in question[reset:]


def test_new_message_sits_in_the_dock_above_the_turn_bar():
    # Live bug (Opera, ~1900 px): the sticky button floated over the interviewer's line. It is now a
    # right-aligned row inside the dock (which has its own background), never over the transcript.
    scroll = JS[JS.index("function scrollTo(el)"):JS.index('newLine.addEventListener("click"')]
    assert "dock.prepend(newLine)" in scroll and "log.after(newLine)" in scroll  # the coding room has no dock
    assert ".dock > .new-line { position: static; justify-self: end;" in CSS


def _browser():
    return next((b for b in BROWSERS if b and Path(b).is_file()), None)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def recorded(monkeypatch, tmp_path):
    """A mixed quant session on the real bank with fake models, as the browser would receive it."""
    from test_mixed_interview import Models, play
    models = Models()
    monkeypatch.setattr(voice_routes, "provider", lambda: models)
    events, _ = play({"pack": "quant", "role": "quant_trading", "topics": ["Probability", "Market making"], "level": "Easy"})
    assert any(e.get("text") == mixed.FORMATS["market"].transition for e in events)
    path = tmp_path / "events.json"
    path.write_text(json.dumps(events), encoding="utf-8")
    return path


@pytest.fixture
def server():
    import uvicorn
    from app.main import app
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None))  # leave logging (and caplog) alone
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=10)


def _run_browser_check(recorded, server, tmp_path):
    node, browser = shutil.which("node"), _browser()
    if not node or not browser:
        pytest.skip("Needs Node and a Chromium browser (Edge or Chrome) for the headless check.")
    result = subprocess.run([node, str(ROOT / "tests" / "market_switch_browser.cjs"), str(recorded), server, browser,
                             str(tmp_path / "profile")], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_room_stays_in_view_when_a_mixed_interview_switches_to_market_making(recorded, server, tmp_path):
    _run_browser_check(recorded, server, tmp_path)


def test_browser_startup_waits_when_the_debugger_has_no_page_yet(recorded, server, tmp_path, monkeypatch):
    # A reachable debugger can return [] while its first page is still opening.
    # Keep it empty for one second, then let the real browser interaction proceed.
    preload = tmp_path / "delay-page.cjs"
    preload.write_text('''
const originalFetch = globalThis.fetch;
let firstReady;
globalThis.fetch = async (...args) => {
  if (!/^http:\\/\\/127\\.0\\.0\\.1:\\d+\\/json\\/list$/.test(String(args[0]))) {
    return originalFetch(...args);
  }
  if (firstReady !== undefined && Date.now() - firstReady < 1000) {
    return Response.json([]);
  }
  const response = await originalFetch(...args);
  if (firstReady === undefined && response.ok) {
    firstReady = Date.now();
    return Response.json([]);
  }
  return response;
};
''', encoding="utf-8")
    options = os.environ.get("NODE_OPTIONS", "")
    monkeypatch.setenv("NODE_OPTIONS", f'{options} --require="{preload.as_posix()}"'.strip())
    _run_browser_check(recorded, server, tmp_path)
