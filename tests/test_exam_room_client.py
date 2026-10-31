from pathlib import Path
import shutil
import subprocess

import pytest


def test_help_offer_never_fires_over_candidate_speech():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the isolated JavaScript unit check.")
    result = subprocess.run([node, str(Path(__file__).with_name("exam_room_unit.cjs"))],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_profile_rating_maths_and_storage():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the isolated JavaScript unit check.")
    result = subprocess.run([node, str(Path(__file__).with_name("profile_unit.cjs"))],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_accounts_merge_sync_and_delete_with_the_sdk_faked():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the isolated JavaScript unit check.")
    result = subprocess.run([node, str(Path(__file__).with_name("account_unit.cjs"))],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
