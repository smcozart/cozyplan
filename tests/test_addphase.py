"""`addphase`: the tool stamps phase structure so the model never renumbers HTML."""

import re

from conftest import read, sidecar_events


def test_addphase_numbers_every_coupled_attribute(pt, new_plan):
    plan = new_plan("ap-num")
    assert pt.main(["addphase", str(plan), "--tasks", "2", "--title", "Second"]) == 0
    text = read(plan)
    assert 'data-phase="2"' in text
    assert 'data-status-for="phase-2"' in text
    for tid in ("2.1", "2.2", "2.3"):
        assert f'data-task="{tid}"' in text
        assert f'data-status-for="{tid}"' in text
    assert "Phase 2: Second" in text
    # --tasks counts work tasks; the Testing Strategy stub is numbered after them
    assert re.search(r"<h4>3\. Testing Strategy</h4>", text)
    assert "{{TESTING_APPROACH" in text


def test_addphase_appends_inside_the_phases_section(pt, new_plan):
    plan = new_plan("ap-place")
    pt.main(["addphase", str(plan), "--tasks", "1"])
    text = read(plan)
    assert text.index('data-phase="1"') < text.index('data-phase="2"')
    assert text.index('data-phase="2"') < text.index('id="validation"')


def test_addphase_repeats_cleanly(pt, new_plan):
    plan = new_plan("ap-repeat")
    for _ in range(3):
        assert pt.main(["addphase", str(plan), "--tasks", "1"]) == 0
    assert pt.phase_numbers(read(plan)) == ["1", "2", "3", "4"]


def test_addphase_output_is_valid_and_addressable(pt, new_plan, capsys):
    plan = new_plan("ap-valid")
    pt.main(["addphase", str(plan), "--tasks", "2", "--title", "Build It"])
    # the ids it stamped are exactly the ids `status` can flip
    assert pt.main(["status", str(plan), "--id", "2.3", "--state", "x"]) == 0
    assert pt.main(["status", str(plan), "--id", "phase-2", "--state", "wip"]) == 0
    capsys.readouterr()
    assert pt.main(["validate", str(plan)]) == 0  # draft: {{}} tokens are only a warning
    out = capsys.readouterr().out
    assert "OK" in out
    assert "duplicate" not in out
    assert "not a gapless" not in out
    assert "must match" not in out


def test_addphase_is_readable_via_phase(pt, new_plan, capsys):
    plan = new_plan("ap-read")
    pt.main(["addphase", str(plan), "--tasks", "2", "--title", "Ship It"])
    capsys.readouterr()
    assert pt.main(["phase", str(plan), "--id", "phase-2"]) == 0
    out = capsys.readouterr().out
    assert "Phase 2: Ship It" in out
    assert "2.1" in out and "2.2" in out and "2.3" in out
    assert "Testing Strategy" in out


def test_addphase_leaves_the_name_as_a_slot_without_title(pt, new_plan):
    plan = new_plan("ap-slot")
    pt.main(["addphase", str(plan), "--tasks", "1"])
    assert "{{PHASE_NAME}}" in read(plan)


def test_addphase_escapes_the_title(pt, new_plan):
    plan = new_plan("ap-escape")
    pt.main(["addphase", str(plan), "--tasks", "1", "--title", "A & B <fast>"])
    assert "A &amp; B &lt;fast&gt;" in read(plan)


def test_addphase_preserves_the_plan_newline(pt, new_plan):
    plan = new_plan("ap-crlf")
    with open(plan, "r", encoding="utf-8", newline="") as f:
        text = f.read()
    with open(plan, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\n", "\r\n"))
    pt.main(["addphase", str(plan), "--tasks", "1"])
    after = read(plan)
    assert "\r\n" in after
    assert re.search(r"(?<!\r)\n", after) is None  # no bare LF sneaked in


def test_addphase_rejects_zero_tasks(pt, new_plan, capsys):
    plan = new_plan("ap-zero")
    before = read(plan)
    capsys.readouterr()
    code = pt.main(["addphase", str(plan), "--tasks", "0"])
    assert code != 0
    assert "--tasks must be >= 1" in capsys.readouterr().err
    assert read(plan) == before


def test_addphase_logs_an_event(pt, new_plan):
    plan = new_plan("ap-event")
    pt.main(["addphase", str(plan), "--tasks", "2", "--title", "T"])
    events = [e for e in sidecar_events(plan) if e["event"] == "addphase"]
    assert len(events) == 1
    assert events[0]["details"] == {"phase": 2, "tasks": 2, "title": "T"}


def test_addphase_stamps_modified(pt, new_plan):
    plan = new_plan("ap-modified")
    before = pt.split_list(pt.parse_meta(read(plan))["modified"])
    pt.main(["addphase", str(plan), "--tasks", "1"])
    after = pt.split_list(pt.parse_meta(read(plan))["modified"])
    assert len(after) >= len(before)


def test_addphase_missing_plan_fails(pt, specs, capsys):
    code = pt.main(["addphase", str(specs / "ghost.html"), "--tasks", "1"])
    assert code != 0
    assert "plan not found" in capsys.readouterr().err
