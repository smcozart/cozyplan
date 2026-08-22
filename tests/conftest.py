"""Shared fixtures and helpers for the cozyplan regression suite.

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
SCRIPTS = REPO / "skills" / "cozyplan" / "scripts"
PLAN_TOOL_PY = SCRIPTS / "plan_tool.py"
GUARD_HOOK = SCRIPTS / "hooks" / "guard_plan_edit.py"
LINT_HOOK = SCRIPTS / "hooks" / "lint_plan.py"
STEER_HOOK = SCRIPTS / "hooks" / "steer_build.py"
DRIFT_HOOK = SCRIPTS / "hooks" / "report_drift.py"

# NTFS has no POSIX exec bit: chmod(0o755) is a no-op there and git for Windows runs
# hooks through sh regardless, so asserting the bit tests the filesystem, not the code.
EXEC_BIT_IS_MEANINGFUL = os.name != "nt"


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


@pytest.fixture
def filled_plan(pt, new_plan):
    """A scaffolded plan with every {{}} placeholder stripped, so it validates and
    may legally leave draft (meta status now gates on leftover placeholders)."""
    import re as _re

    def _make(name="filled-plan", title="Filled Plan", owner=None):
        plan = new_plan(name, title, owner)
        with open(plan, "r", encoding="utf-8", newline="") as f:
            text = f.read()
        text = _re.sub(r"\{\{.*?\}\}", "x", text, flags=_re.S)
        with open(plan, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return plan
    return _make


def git(cwd: Path, *args: str):
    # stdin=DEVNULL, never inherited. Under pytest the parent's stdin is a captured
    # handle, and on Windows a child that closes it leaves every later spawn raising
    # WinError 6 at Popen — which surfaces as dozens of unrelated fixture errors.
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    """A tmp git repo with one commit; skips the test if git is unavailable.

    Isolated from the developer's global and system gitconfig. Without this, a test
    that unsets local user.name still sees the machine's global identity and asserts
    the opposite of what a bare CI runner produces — green on the runner, red on a
    laptop, for a reason that has nothing to do with the code."""
    # GLOBAL only, never SYSTEM: Git for Windows keeps core settings (notably
    # line-ending handling) in the system config, and blanking it changes how files
    # are written — which broke commit-order rendering while hiding nothing useful.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global-gitconfig"))
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
    e.pop("COZYPLAN_ROLE", None)
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
