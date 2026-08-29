"""`trailers` + `hooks git-install`: advisory trailer injection (ADR-0004, ADR-0007).

The hook adds only what it can demonstrate and never rejects, so these tests pin
both halves: that a provable trailer appears, and that an unprovable one does not.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess

import pytest

from conftest import EXEC_BIT_IS_MEANINGFUL, PLAN_TOOL_PY, git, read

# Git for Windows runs hooks through its own bundled sh, so the two tests that
# drive a real `git commit` cover this contract on every platform. These two
# invoke a hook DIRECTLY, which needs an sh this process can spawn.
SH = shutil.which("sh") or shutil.which("bash")


def infer(pt, repo, capsys):
    pt.main(["trailers", "--root", str(repo), "--print"])
    return [l for l in capsys.readouterr().out.strip().split("\n") if l]


def stage_adr(repo, num, name="a-decision"):
    adr = repo / "docs" / "adr"
    adr.mkdir(parents=True, exist_ok=True)
    (adr / f"{num}-{name}.md").write_text(f"---\ntitle: T{num}\n---\n", encoding="utf-8")
    git(repo, "add", "-A")


def test_staged_adr_is_inferred(pt, git_repo, capsys):
    stage_adr(git_repo, "0007")
    assert infer(pt, git_repo, capsys) == ["ADR: 0007"]


def test_multiple_staged_adrs_are_sorted_and_joined(pt, git_repo, capsys):
    stage_adr(git_repo, "0009", "later")
    stage_adr(git_repo, "0002", "earlier")
    assert infer(pt, git_repo, capsys) == ["ADR: 0002,0009"]


def test_nothing_staged_infers_nothing(pt, git_repo, capsys):
    assert infer(pt, git_repo, capsys) == []


def test_branch_naming_a_real_plan_infers_it(pt, git_repo, specs, capsys):
    (git_repo / "specs").mkdir(exist_ok=True)
    (git_repo / "specs" / "streaming-ingest.html").write_text("<html></html>", encoding="utf-8")
    git(git_repo, "checkout", "-q", "-b", "feat/streaming-ingest")
    assert infer(pt, git_repo, capsys) == ["Plan: streaming-ingest"]


def test_branch_with_no_matching_plan_infers_nothing(pt, git_repo, capsys):
    """Never a guess: a branch name alone is not evidence a plan exists."""
    git(git_repo, "checkout", "-q", "-b", "feat/no-such-plan")
    assert infer(pt, git_repo, capsys) == []


def test_verified_is_never_inferred(pt, git_repo, capsys):
    """No hook can prove a test ran, so it must never claim one did."""
    stage_adr(git_repo, "0007")
    assert not any(t.startswith("Verified:") for t in infer(pt, git_repo, capsys))


def test_message_file_is_amended_in_place(pt, git_repo, tmp_path):
    stage_adr(git_repo, "0007")
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("feat: a change\n\nsome body text\n", encoding="utf-8")
    assert pt.main(["trailers", "--root", str(git_repo), "--message-file", str(msg)]) == 0
    out = read(msg)
    assert "ADR: 0007" in out
    assert out.strip().split("\n")[-1] == "ADR: 0007", "trailer must be the last line"


def test_existing_trailer_is_not_duplicated(pt, git_repo, tmp_path):
    stage_adr(git_repo, "0007")
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("feat: a change\n\nADR: 0007\n", encoding="utf-8")
    pt.main(["trailers", "--root", str(git_repo), "--message-file", str(msg)])
    assert read(msg).count("ADR: 0007") == 1


def test_injection_survives_a_co_authored_by_line(pt, git_repo, tmp_path):
    """The bug this session hit by hand: a trailer block split by a blank line
    means git parses only the last paragraph. interpret-trailers gets it right."""
    stage_adr(git_repo, "0007")
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("feat: a change\n\nbody\n\nCo-Authored-By: X <x@example.com>\n",
                   encoding="utf-8")
    pt.main(["trailers", "--root", str(git_repo), "--message-file", str(msg)])
    got = git(git_repo, "interpret-trailers", "--parse", str(msg)).stdout
    assert "ADR: 0007" in got and "Co-Authored-By" in got


def test_missing_message_file_is_not_an_error(pt, git_repo):
    """Fail open: a hook that breaks a commit because a file moved is worse than
    a missing trailer (ADR-0004)."""
    stage_adr(git_repo, "0007")
    assert pt.main(["trailers", "--root", str(git_repo),
                    "--message-file", str(git_repo / "nope")]) == 0


def test_git_install_writes_executable_hooks_and_sets_hookspath(pt, git_repo, capsys):
    assert pt.main(["hooks", "git-install", "--root", str(git_repo)]) == 0
    hooks = git_repo / ".githooks"
    for name in ("commit-msg", "pre-push"):
        p = hooks / name
        assert p.exists(), name
        if EXEC_BIT_IS_MEANINGFUL:
            assert os.stat(p).st_mode & stat.S_IXUSR, f"{name} must be executable"
    assert git(git_repo, "config", "core.hooksPath").stdout.strip() == ".githooks"
    assert git(git_repo, "config", "cozyplan.plantool").stdout.strip().endswith("plan_tool.py")


def test_git_remove_unsets_everything(pt, git_repo):
    pt.main(["hooks", "git-install", "--root", str(git_repo)])
    assert pt.main(["hooks", "git-remove", "--root", str(git_repo)]) == 0
    assert not (git_repo / ".githooks" / "commit-msg").exists()
    assert git(git_repo, "config", "core.hooksPath").stdout.strip() == ""


def test_installed_hook_injects_on_a_real_commit(pt, git_repo):
    """End to end: the hook git actually runs, on a commit actually made."""
    pt.main(["hooks", "git-install", "--root", str(git_repo)])
    stage_adr(git_repo, "0007")
    r = git(git_repo, "commit", "-m", "feat: add a decision")
    assert r.returncode == 0, r.stderr
    body = git(git_repo, "log", "-1", "--format=%B").stdout
    assert "ADR: 0007" in body, body


def _wrapper_at_spaced_path(tmp_path, name="py"):
    """A runner whose path contains a space, wrapping the current interpreter.

    The workspace this project is developed in lives under `.../AI Dev/software
    factory/`, so a spaced interpreter path is the normal case here, not an exotic one.
    """
    import sys as _sys
    d = tmp_path / "dir with a space" / "bin"
    d.mkdir(parents=True, exist_ok=True)
    w = d / name
    w.write_text('#!/bin/sh\nexec "%s" "$@"\n' % _sys.executable, encoding="utf-8")
    w.chmod(0o755)
    return w


def test_hook_runs_when_the_interpreter_path_contains_spaces(pt, git_repo, tmp_path):
    """Regression: the hook quoted nothing, so a spaced runner word-split, the
    command was not found, and `|| true` swallowed it — the trailer vanished with
    no error anywhere. Silent fail-open is the failure ADR-0004 exists to prevent."""
    pt.main(["hooks", "git-install", "--root", str(git_repo)])
    git(git_repo, "config", "cozyplan.runner", str(_wrapper_at_spaced_path(tmp_path)))
    git(git_repo, "config", "--unset", "cozyplan.runnerarg")
    stage_adr(git_repo, "0007")
    r = git(git_repo, "commit", "-m", "feat: add a decision")
    assert r.returncode == 0, r.stderr
    assert "ADR: 0007" in git(git_repo, "log", "-1", "--format=%B").stdout


def test_git_install_records_runner_as_separate_parts(pt, git_repo):
    """The runner is stored as executable + optional arg so the hook can quote the
    executable. Joining them into one string is what made spaces unquotable."""
    pt.main(["hooks", "git-install", "--root", str(git_repo)])
    exe = git(git_repo, "config", "cozyplan.runner").stdout.strip()
    arg = git(git_repo, "config", "cozyplan.runnerarg").stdout.strip()
    assert exe and " " not in arg
    assert arg in ("", "run")
    if arg == "run":
        assert exe == "uv"


def test_doctor_reports_a_broken_stored_runner(pt, git_repo, capsys):
    """doctor tested its own resolution, so it reported ok while the installed hook
    was dead. It must test what the clone actually recorded."""
    pt.main(["hooks", "git-install", "--root", str(git_repo)])
    git(git_repo, "config", "cozyplan.runner", "/nonexistent/interpreter")
    git(git_repo, "config", "--unset", "cozyplan.runnerarg")
    pt.main(["doctor", "--root", str(git_repo)])
    out = capsys.readouterr().out
    assert "hook interpreter" in out
    line = [l for l in out.splitlines() if "hook interpreter" in l][0]
    assert "gap" in line, line
    assert "fail open" in line, line


# ── which plan_tool the git hooks run (reported by cozycode) ─────────────────
# `git-install` used to record `Path(__file__).resolve()` — wherever the tool was
# invoked from. A repo wired from a maintainer's checkout then ran THAT checkout's
# plan_tool to answer "is this repo healthy", while carrying a vendored copy of its
# own, and `doctor` counted hook files without ever saying which tool they ran.

def test_git_install_records_an_in_repo_tool_relatively(pt, git_repo):
    """Relative, so it survives the repo moving or being cloned elsewhere. Git runs
    hooks from the worktree top level, so a relative path resolves there."""
    vendored = git_repo / ".claude" / "skills" / "cozyplan" / "scripts"
    vendored.mkdir(parents=True)
    (vendored / "plan_tool.py").write_bytes(pt.Path(pt.__file__).resolve().read_bytes())

    assert pt.main(["hooks", "git-install", "--root", str(git_repo)]) == 0
    recorded = git(git_repo, "config", "cozyplan.plantool").stdout.strip()
    assert recorded == ".claude/skills/cozyplan/scripts/plan_tool.py", recorded
    assert not pt.Path(recorded).is_absolute(), "an absolute path pins this to one machine"


def test_doctor_names_a_tool_outside_the_worktree(pt, git_repo, capsys):
    """The row that was missing: `git hooks` counts files and never opens one, so it
    passed while the hooks executed a plan_tool from another repository entirely."""
    git(git_repo, "config", "core.hooksPath", ".githooks")
    (git_repo / ".githooks").mkdir(exist_ok=True)
    (git_repo / ".githooks" / "commit-msg").write_text("#!/bin/sh\n", encoding="utf-8")
    outside = pt.Path(pt.__file__).resolve()
    git(git_repo, "config", "cozyplan.plantool", str(outside))

    pt.main(["doctor", "--root", str(git_repo)])
    out = capsys.readouterr().out
    assert "git hook tool" in out
    assert "OUTSIDE this repo" in out, out


def test_doctor_flags_an_unset_hook_tool_as_a_silent_no_op(pt, git_repo, capsys):
    """Both hooks open with `TOOL=$(git config ...) || exit 0`. Unset means they run
    nothing, on every machine but the one that wired them."""
    pt.main(["doctor", "--root", str(git_repo)])
    out = capsys.readouterr().out
    assert "cozyplan.plantool unset" in out, out


def test_doctor_flags_a_recorded_tool_that_does_not_exist(pt, git_repo, capsys):
    git(git_repo, "config", "cozyplan.plantool", "does/not/exist/plan_tool.py")
    pt.main(["doctor", "--root", str(git_repo)])
    assert "does not exist" in capsys.readouterr().out


# ── the hook's own absence (ADR-0010, third registration path) ───────────────
# Both hooks used to end in `|| true`. A recorded runner that had left the host
# produced no trailer, no output and exit 0 — the same trace a healthy commit with
# nothing to add leaves. These pin the two halves that must never merge again:
# the commit still succeeds, and the failure is on stderr where a terminal shows it.

def test_a_recorded_runner_that_left_the_host_is_reported_and_recovered(pt, git_repo):
    """uv gets uninstalled. The record outlives it, so the hook re-resolves rather
    than going quiet, and says the record is stale."""
    pt.main(["hooks", "git-install", "--root", str(git_repo)])
    git(git_repo, "config", "cozyplan.runner", "uv-is-not-installed-here")
    git(git_repo, "config", "cozyplan.runnerarg", "run")
    stage_adr(git_repo, "0007")

    r = git(git_repo, "commit", "-m", "feat: add a decision")
    assert r.returncode == 0, "an advisory hook must never reject a commit (ADR-0004)"
    assert "uv-is-not-installed-here" in r.stderr, r.stderr
    assert "not on PATH" in r.stderr, r.stderr
    # Recovered, not merely reported: the trailer still lands via the probe.
    assert "ADR: 0007" in git(git_repo, "log", "-1", "--format=%B").stdout


def test_a_missing_plan_tool_is_reported_not_swallowed(pt, git_repo):
    """The half-wired clone: hooks installed, cozyplan.plantool pointing at nothing."""
    pt.main(["hooks", "git-install", "--root", str(git_repo)])
    git(git_repo, "config", "cozyplan.plantool", "does/not/exist/plan_tool.py")
    stage_adr(git_repo, "0007")

    r = git(git_repo, "commit", "-m", "feat: add a decision")
    assert r.returncode == 0, "an advisory hook must never reject a commit (ADR-0004)"
    assert "half-wired" in r.stderr, r.stderr
    assert "ADR: 0007" not in git(git_repo, "log", "-1", "--format=%B").stdout


@pytest.mark.skipif(os.name == "nt", reason=(
    "the test replaces PATH wholesale and drives a #!/bin/sh stub; on Windows the "
    "shell itself needs %SystemRoot% and %ComSpec% back, and re-adding those re-adds "
    "the directories this test exists to empty. Covered on POSIX only, deliberately."))
def test_no_interpreter_on_the_host_is_reported(pt, git_repo, tmp_path):
    """The bare host. PATH holds a `git config` stand-in and nothing else — no
    python3, python, py or uv — so every probe fails and the hook must say so.

    A stub rather than the real git: on macOS python3 and git share /usr/bin, so
    a PATH that keeps git keeps an interpreter too and the branch never runs.
    """
    pt.main(["hooks", "git-install", "--root", str(git_repo)])
    bindir = tmp_path / "bare-bin"
    bindir.mkdir()
    stub = bindir / "git"
    stub.write_text(
        '#!/bin/sh\n'
        '[ "$1" = config ] || exit 1\n'
        'case "$2" in\n'
        '  cozyplan.plantool) echo "%s" ;;\n'
        '  *) exit 1 ;;\n'
        'esac\n' % PLAN_TOOL_PY,
        encoding="utf-8",
    )
    stub.chmod(0o755)

    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("feat: something\n", encoding="utf-8")
    r = subprocess.run(
        ["/bin/sh", str(git_repo / ".githooks" / "commit-msg"), str(msg)],
        capture_output=True, text=True, env={"PATH": str(bindir)},
    )
    assert r.returncode == 0, "advisory: a bare host must not block the commit"
    assert "no Python 3.9+ resolved" in r.stderr, r.stderr
    assert msg.read_text(encoding="utf-8") == "feat: something\n", "message untouched"


@pytest.mark.skipif(SH is None, reason="no sh/bash this process can spawn")
def test_pre_push_reports_a_crash_that_produces_no_findings(pt, git_repo, tmp_path):
    """`state check` exits non-zero on a real finding too, so the exit code alone
    cannot separate a finding from a crash. A crash prints no report; that pairing
    is what gets reported."""
    pt.main(["hooks", "git-install", "--root", str(git_repo)])
    broken = git_repo / "broken_tool.py"
    broken.write_text("raise SystemExit('boom: not a plan_tool')\n", encoding="utf-8")
    git(git_repo, "config", "cozyplan.plantool", "broken_tool.py")
    git(git_repo, "config", "--unset", "cozyplan.runner")
    git(git_repo, "config", "--unset", "cozyplan.runnerarg")

    r = subprocess.run(
        [SH, str(git_repo / ".githooks" / "pre-push")],
        capture_output=True, text=True, cwd=str(git_repo), stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 0, "pre-push never blocks (ADR-0004)"
    assert "with no report" in r.stderr, r.stderr
    assert "boom" in r.stderr, r.stderr
