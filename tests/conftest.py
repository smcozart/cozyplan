"""Shared fixtures and helpers for the planf3 regression suite.

plan_tool is loaded as an in-process module (fast) and its commands are driven
through `plan_tool.main(argv)`, which returns the process exit code. The two hooks
are stdin/stdout protocols, so they are exercised via subprocess (see run_hook).

All artifacts land in pytest's tmp_path — nothing is ever written inside the repo's
own specs/ or roles/. The plan template is read from the repo (never written).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PLAN_TOOL_PY = REPO / "scripts" / "plan_tool.py"
GUARD_HOOK = REPO / "scripts" / "hooks" / "guard_plan_edit.py"
LINT_HOOK = REPO / "scripts" / "hooks" / "lint_plan.py"


def _load_plan_tool():
    # Don't drop a __pycache__ into the repo's scripts/ dir when importing.
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("plan_tool_under_test", PLAN_TOOL_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def pt():
    """The plan_tool module, imported once per session."""
    return _load_plan_tool()


@pytest.fixture
def specs(tmp_path):
    d = tmp_path / "specs"
    d.mkdir()
    return d


@pytest.fixture
def new_plan(pt, specs):
    """Callable that scaffolds a fresh plan into the tmp specs dir and returns its path."""
    def _make(name="sample-plan", title="Sample Plan", owner=None):
        argv = ["new", name, "--title", title, "--specs", str(specs)]
        if owner:
            argv += ["--owner", owner]
        code = pt.main(argv)
        assert code == 0, f"scaffolding {name} failed (exit {code})"
        return specs / f"{name}.html"
    return _make


def git(cwd: Path, *args: str):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path):
    """A tmp git repo with one commit; skips the test if git is unavailable."""
    r = git(tmp_path, "init")
    if r.returncode != 0:
        pytest.skip("git not available")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "README.md").write_text("seed\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "init")
    return tmp_path


def read(path: Path) -> str:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def sidecar_events(plan_path: Path) -> list[dict]:
    """Parse the NDJSON event sidecar for a plan into a list of records."""
    log = Path(plan_path).with_suffix(".log.ndjson")
    if not log.exists():
        return []
    out = []
    for line in read(log).splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def run_hook(hook_path: Path, payload: dict, env: dict | None = None):
    """Run a hook script as a subprocess, feeding `payload` as JSON on stdin."""
    e = os.environ.copy()
    e.pop("PLANF3_ROLE", None)
    e.pop("CLAUDE_PLUGIN_ROOT", None)
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=e,
    )


def hook_decision(result) -> dict | None:
    """Parse a guard-hook stdout into its hookSpecificOutput dict, or None if silent."""
    out = result.stdout.strip()
    if not out:
        return None
    return json.loads(out).get("hookSpecificOutput")
