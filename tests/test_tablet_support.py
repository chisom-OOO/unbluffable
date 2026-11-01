"""Decision log 35: the interview, setup, profile and report run on tablets; phones stay gated."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
TEMPLATES = ROOT / "app" / "templates"
PAGES = ["end", "forge", "interview", "landing", "profile", "welcome"]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_device_rules_resampling_voices_and_gate_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the isolated JavaScript unit check.")
    result = subprocess.run([node, str(Path(__file__).with_name("device_unit.cjs"))],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    for line in ("device rules ok", "mic resampling ok", "tablet voice ok", "tablet gate ok"):
        assert line in result.stdout


@pytest.mark.parametrize("page", PAGES)
def test_device_rules_load_before_the_page_scripts(page):
    html = read(TEMPLATES / f"{page}.html")
    order = re.findall(r'src="/ui-static/([\w-]+\.js)"', html)
    assert order.index("device.js") < order.index("ui.js") < order.index("account.js")


def test_the_gate_names_laptops_and_tablets_and_drops_the_touch_rule():
    ui = read(STATIC / "ui" / "ui.js")
    gate = ui[ui.index("function initDesktopGate"):ui.index("window.UB = {")]
    assert "Open this on a laptop or tablet" in gate and "desktop" not in gate.split("innerHTML")[1].lower()
    tooSmall = ui[ui.index("const tooSmall"):ui.index("const desktopOnly")]
    assert "phoneSized" in tooSmall and "pointer" not in tooSmall and "900" not in tooSmall


def test_start_unlocks_audio_and_speech_inside_the_tap():
    js = read(STATIC / "ui" / "interview.js")
    begin = js[js.index("async function begin()"):js.index('start.addEventListener("click", begin)')]
    first_await = begin.index("await ")
    assert begin.index("voice.unlock()") < first_await and begin.index("window.UB.unlockSpeech()") < first_await
    # The device check's microphone test also creates the audio context in the tap.
    assert re.search(r'\$\("mic-test"\)\.addEventListener\("click", \(\) => \{ voice\.unlock\(\); testMic', js)


def test_nothing_only_works_on_hover():
    """Hover may restyle, never reveal: no :hover rule shows, hides or fades anything, and no
    script listens for mouse-over events."""
    for css in [STATIC / "ui" / "exam-room.css", STATIC / "voice.css"]:
        for selectors, body in re.findall(r"([^{}]*:hover[^{}]*)\{([^{}]*)\}", read(css)):
            assert not re.search(r"\b(display|visibility|opacity)\s*:", body), (css.name, selectors.strip())
    for js in (STATIC / "ui").glob("*.js"):
        assert not re.search(r"mouse(enter|over|leave|out)", read(js)), js.name


def test_viewport_height_is_dynamic():
    for css in [STATIC / "ui" / "exam-room.css", STATIC / "voice.css"]:
        text = read(css)
        for m in re.finditer(r"100vh", text):
            rule = text[m.start():text.index("}", m.start())]
            assert "100dvh" in rule, f"{css.name}: 100vh without a 100dvh override"


def test_touch_targets_are_44px_on_touch_screens():
    css = read(STATIC / "ui" / "exam-room.css")
    block = css[css.index("@media (pointer: coarse)"):]
    block = block[:block.index("\n}")]
    for selector in [".btn-small", ".linkbtn", ".topic-chip", ".icon-btn", ".icon-btn-small", ".ws-banner-close", ".checkline",
                     '.ws-tabs [role="tab"]', ".mic-device select", ".role-option", ".profile-link"]:
        assert selector in block, selector
    assert "min-height: 44px" in block and "width: 44px; height: 44px" in block
    # The editor follows the visual viewport while the on-screen keyboard is open.
    assert "body.coding-mode.keyboard-open .shell" in css and "var(--vv-h, 100dvh)" in css


def test_coding_round_recommends_a_keyboard_on_touch_only_devices():
    js = read(STATIC / "ui" / "coding-ui.js")
    assert "A keyboard is recommended for the coding round." in js
    note = js[js.index("if (window.UB.touchOnly())"):]
    assert note.index("A keyboard is recommended") < note.index("}")
    assert "window.visualViewport" in js and "viewportFrame" in js and 'addEventListener("resize", fit)' in js
    html = read(TEMPLATES / "interview.html")
    assert re.search(r'<textarea id="code-editor"[^>]*autocapitalize="off"[^>]*autocorrect="off"', html)


def test_google_sign_in_redirects_on_iphone_and_ipad():
    account = read(STATIC / "ui" / "account.js")
    assert "redirect: window.UB.appleTouch()" in account
    ui = read(STATIC / "ui" / "ui.js")
    assert "window.UBDevice.appleTouch(navigator)" in ui
