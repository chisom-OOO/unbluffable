"""The Docker image must hold every local package the web app imports. A missing `COPY forge`
broke every deploy from PR #4 until PR #10: app/byoq.py imports forge, and uvicorn failed at
startup. This walks the imports of app/ (and of every local package they reach) with ast."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def local(name):
    return (ROOT / name / "__init__.py").exists() or (ROOT / f"{name}.py").exists()


def top_level_imports(package):
    found = set()
    files = [ROOT / f"{package}.py"] if (ROOT / f"{package}.py").exists() else (ROOT / package).rglob("*.py")
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def reached_from_app():
    seen, todo = set(), ["app"]
    while todo:
        package = todo.pop()
        if package in seen:
            continue
        seen.add(package)
        todo.extend(name for name in top_level_imports(package) if local(name) and name not in seen)
    return seen


def copied():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    return {m.group(1).rstrip("/") for m in re.finditer(r"^COPY\s+(?:--\S+\s+)*(\S+)\s+\S+\s*$", text, re.M)}


def test_every_local_package_the_app_imports_is_copied_into_the_image():
    needed = reached_from_app()
    assert {"app", "engine", "llm", "voice", "forge"} <= needed  # the walk itself works
    missing = sorted(needed - copied())
    assert not missing, f"Dockerfile has no COPY for: {missing}"


def test_the_check_catches_a_missing_copy(monkeypatch):
    original = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    without_forge = "\n".join(line for line in original.splitlines() if not line.startswith("COPY forge"))
    monkeypatch.setattr(Path, "read_text", lambda self, encoding=None: without_forge
                        if self.name == "Dockerfile" else Path.read_bytes(self).decode(encoding or "utf-8"))
    assert "forge" in reached_from_app() - copied()
