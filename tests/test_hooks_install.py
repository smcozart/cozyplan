"""Tests for `plan_tool hooks install|remove` — hook registration for
bare-skill installs (npx skills add), where no plugin manifest registers
the coherence hooks automatically."""
from __future__ import annotations

import json


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_install_creates_settings_with_both_entries(pt, tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    assert pt.main(["hooks", "install", "--settings", str(settings)]) == 0
    data = read(settings)
    pre = data["hooks"]["PreToolUse"]
    post = data["hooks"]["PostToolUse"]
    assert len(pre) == 1 and len(post) == 1
    assert pre[0]["matcher"] == "Edit|MultiEdit|Write"
    assert "guard_plan_edit.py" in pre[0]["hooks"][0]["command"]
    # It used to resolve the interpreter at INSTALL time and write `uv run <abs path>`.
    # That is right on exactly one machine at one moment: a host that later loses uv,
    # or a colleague who never had it, gets a registered hook that cannot start and
    # says nothing. Registration now goes through run-hook.sh, which resolves at CALL
    # time and fails loud, so both this route and the plugin manifest behave the same.
    # Parsed, not string-matched: these paths contain spaces and are quoted.
    import shlex as _shlex
    argv = _shlex.split(pre[0]["hooks"][0]["command"])
    assert argv[0] == "sh"
    assert argv[1].endswith("run-hook.sh"), f"not launched through the resolver: {argv}"
    assert argv[2].endswith("guard_plan_edit.py")
    assert int(argv[3]) == pt.HOOK_DEAD_EXIT["guard_plan_edit.py"]
    # No interpreter may be named here — that was the whole bug.
    assert "uv run" not in pre[0]["hooks"][0]["command"]
    assert post[0]["matcher"] == "Edit|MultiEdit|Write|Bash"
    assert "lint_plan.py" in post[0]["hooks"][0]["command"]


def test_install_is_idempotent(pt, tmp_path):
    settings = tmp_path / "settings.json"
    assert pt.main(["hooks", "install", "--settings", str(settings)]) == 0
    assert pt.main(["hooks", "install", "--settings", str(settings)]) == 0
    data = read(settings)
    assert len(data["hooks"]["PreToolUse"]) == 1
    assert len(data["hooks"]["PostToolUse"]) == 1


def test_install_preserves_unrelated_settings_and_hooks(pt, tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "permissions": {"allow": ["Bash(ls*)"]},
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo other"}]},
        ]},
    }), encoding="utf-8")
    assert pt.main(["hooks", "install", "--settings", str(settings)]) == 0
    data = read(settings)
    assert data["permissions"] == {"allow": ["Bash(ls*)"]}
    cmds = [blk["hooks"][0]["command"] for blk in data["hooks"]["PreToolUse"]]
    assert any("echo other" in c for c in cmds)
    assert any("guard_plan_edit.py" in c for c in cmds)


def test_remove_strips_only_our_entries(pt, tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "hooks": {"PostToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo other"}]},
        ]},
    }), encoding="utf-8")
    assert pt.main(["hooks", "install", "--settings", str(settings)]) == 0
    assert pt.main(["hooks", "remove", "--settings", str(settings)]) == 0
    data = read(settings)
    assert "PreToolUse" not in data["hooks"]
    cmds = [blk["hooks"][0]["command"] for blk in data["hooks"]["PostToolUse"]]
    assert cmds == ["echo other"]


def test_remove_drops_empty_hooks_key(pt, tmp_path):
    settings = tmp_path / "settings.json"
    assert pt.main(["hooks", "install", "--settings", str(settings)]) == 0
    assert pt.main(["hooks", "remove", "--settings", str(settings)]) == 0
    assert "hooks" not in read(settings)


def test_install_rejects_malformed_settings(pt, tmp_path, capsys):
    settings = tmp_path / "settings.json"
    settings.write_text("not json", encoding="utf-8")
    assert pt.main(["hooks", "install", "--settings", str(settings)]) == 1
    assert "cannot parse" in capsys.readouterr().err


def test_the_registered_command_is_runnable_on_this_machine(pt, tmp_path):
    """The bug this closes: the hook was registered and unrunnable at the same time,
    and doctor reported it as ok because it checked registration, not runnability."""
    import shlex, subprocess
    settings = tmp_path / ".claude" / "settings.json"
    pt.main(["hooks", "install", "--settings", str(settings)])
    cmd = read(settings)["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    # Claude Code substitutes this before the shell sees it; do the same here.
    cmd = cmd.replace("${CLAUDE_PROJECT_DIR}", str(pt.Path(".").resolve()))
    argv = shlex.split(cmd)
    r = subprocess.run(argv, input="{}", capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"registered hook is not runnable: {cmd}\n{r.stderr[:300]}"


def test_registration_inside_a_project_is_portable(pt, tmp_path):
    """.claude/settings.json is committed, so an absolute path in it is correct on
    one machine and wrong on every teammate's. When the scripts live inside the
    project, the registration must be written against ${CLAUDE_PROJECT_DIR}."""
    settings = tmp_path / ".claude" / "settings.json"
    repo_root = pt.Path(pt.__file__).resolve().parents[3]
    pt.main(["hooks", "install", "--settings", str(settings), "--root", str(repo_root)])
    cmd = read(settings)["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "${CLAUDE_PROJECT_DIR}" in cmd
    assert str(repo_root) not in cmd, (
        f"an absolute project path leaked into a committed file: {cmd}")


def test_a_vendored_copy_is_registered_over_the_running_tool(pt, tmp_path):
    """`init --vendor` copies the skill into the repo so a clone needs no install.
    Registering the *running* tool instead left the repo with a good vendored copy
    and a committed settings.json naming a path on one person's machine."""
    vendored = tmp_path / ".claude" / "skills" / "cozyplan" / "scripts" / "hooks"
    vendored.mkdir(parents=True)
    src = pt.Path(pt.__file__).resolve().parent / "hooks"
    for f in list(pt.HOOK_MATCHERS) + ["run-hook.sh"]:
        (vendored / f).write_bytes((src / f).read_bytes())

    settings = tmp_path / ".claude" / "settings.json"
    pt.main(["hooks", "install", "--settings", str(settings), "--root", str(tmp_path)])
    cmd = read(settings)["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert ".claude/skills/cozyplan" in cmd, f"did not register the vendored copy: {cmd}"
    assert "${CLAUDE_PROJECT_DIR}" in cmd
    assert str(src) not in cmd, "registered the running tool instead of the vendored copy"


def test_global_registration_stays_absolute(pt, tmp_path):
    """A user-wide settings file is shared across projects, so ${CLAUDE_PROJECT_DIR}
    would re-point it at whichever repo happens to be open."""
    settings = tmp_path / "global.json"
    pt.main(["hooks", "install", "--settings", str(settings), "--global"])
    cmd = read(settings)["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "${CLAUDE_PROJECT_DIR}" not in cmd


def test_plugin_manifest_registers_every_hook_in_HOOK_MATCHERS(pt):
    """The plugin manifest and HOOK_MATCHERS are two registration paths for the
    same four hooks, and they silently disagreed: hooks.json shipped 2 of 4, so
    a plugin install got half the enforcement layer and doctor — which requires
    all of HOOK_MATCHERS — could never report it as wired."""
    manifest = json.loads(pt.PLUGIN_HOOKS_JSON.read_text(encoding="utf-8"))
    registered = {
        (event, blk.get("matcher", ""), h.get("command", ""))
        for event, blocks in manifest["hooks"].items()
        for blk in blocks
        for h in blk.get("hooks", [])
    }
    for script, (event, matcher) in pt.HOOK_MATCHERS.items():
        assert any(
            e == event and m == matcher and script in cmd
            for e, m, cmd in registered
        ), f"{script} ({event}, matcher={matcher!r}) is missing from hooks/hooks.json"
    assert len(registered) == len(pt.HOOK_MATCHERS), "hooks.json registers something HOOK_MATCHERS does not know about"
