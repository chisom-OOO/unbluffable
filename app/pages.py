"""The Exam Room's HTML pages. Each is sent with Cache-Control: no-cache, so a browser
always checks for a new deploy, and its script and stylesheet URLs carry ?v=<version>,
so a new deploy never runs with an old script or stylesheet."""

from __future__ import annotations

import os
import re
import subprocess
import time
from functools import lru_cache
from pathlib import Path

from fastapi.responses import HTMLResponse

TEMPLATES = Path(__file__).parent / "templates"
_ASSET = re.compile(r'((?:src|href)="/ui-static/[^"?]+\.(?:js|css))"')


def _version() -> str:
    """The deploy's commit (Render sets RENDER_GIT_COMMIT), else the local commit, else
    the time this process started."""
    commit = os.environ.get("RENDER_GIT_COMMIT", "").strip()
    if commit:
        return commit[:12]
    try:
        local = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=Path(__file__).parent,
                               capture_output=True, text=True, timeout=5)
        if local.returncode == 0 and local.stdout.strip():
            return local.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return str(int(time.time()))


VERSION = _version()


@lru_cache(maxsize=None)
def render(name: str, version: str = VERSION) -> str:
    html = (TEMPLATES / name).read_text(encoding="utf-8")
    return _ASSET.sub(lambda m: f'{m.group(1)}?v={version}"', html)


def page(name: str) -> HTMLResponse:
    return HTMLResponse(render(name), headers={"Cache-Control": "no-cache"})
