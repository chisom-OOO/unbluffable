from pathlib import Path
import shutil
import subprocess

import pytest


def test_javascript_acknowledgement_order_echo_muting_and_pcm():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the isolated JavaScript unit check.")
    result = subprocess.run([node, str(Path(__file__).with_name("voice_client_unit.cjs"))],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
