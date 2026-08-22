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
    # It used to hardcode `uv run`, so on a machine without uv the registered hook was
    # `uv run …` — command not found, silently. The git-hook half already resolved the
    # runner; this half did not, and doctor reported "registered" either way.
    # Parsed, not string-matched: the interpreter path may contain spaces and be quoted.
    import shlex as _shlex
    exe, arg = pt._hook_runner_parts()
    argv = _shlex.split(pre[0]["hooks"][0]["command"])
    assert argv[0] == exe
    assert (argv[1] == arg) if arg else argv[1].endswith("guard_plan_edit.py")
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
    argv = shlex.split(cmd)
    r = subprocess.run(argv, input="{}", capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"registered hook is not runnable: {cmd}\n{r.stderr[:300]}"


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
