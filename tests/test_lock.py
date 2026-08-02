"""Plan write lock: releases cleanly, breaks (and logs) a stale lock, fails closed."""

import os
import re
import time

from conftest import read, sidecar_events


def _marker(text, sid):
    m = re.search(r'data-status-for="' + re.escape(sid) + r'"[^>]*>(\[[^\]]*\])', text)
    return m.group(1) if m else None


def test_sequential_ops_release_lock(pt, new_plan):
    plan = new_plan("lk")
    assert pt.main(["status", str(plan), "--id", "1.1", "--state", "wip"]) == 0
    assert pt.main(["status", str(plan), "--id", "1.2", "--state", "x"]) == 0
    # lock file is always cleaned up in the finally/release path
    assert not plan.with_suffix(".lock").exists()


def test_stale_lock_is_broken_and_recorded(pt, new_plan, capsys):
    plan = new_plan("lk2")
    lock = plan.with_suffix(".lock")
    lock.write_text("99999 stale", encoding="utf-8")
    old = time.time() - 120  # older than LOCK_STALE_SECONDS
    os.utime(lock, (old, old))

    capsys.readouterr()
    assert pt.main(["status", str(plan), "--id", "1.1", "--state", "wip"]) == 0
    combined = capsys.readouterr()
    assert "stale" in (combined.out + combined.err)
    # the operation went through despite the pre-existing lock
    assert _marker(read(plan), "1.1") == "[wip]"
    assert not lock.exists()

    # ...and the break survives the stderr line that announced it
    breaks = [e for e in sidecar_events(plan) if e["event"] == "lock-stale-break"]
    assert len(breaks) == 1
    assert breaks[0]["details"]["lock"] == lock.name
    assert breaks[0]["details"]["age_seconds"] > pt.LOCK_STALE_SECONDS


def test_busy_lock_fails_closed(pt, new_plan, capsys, monkeypatch):
    plan = new_plan("lk3")
    lock = plan.with_suffix(".lock")
    lock.write_text("1234 live", encoding="utf-8")  # young -> a live holder, not debris
    monkeypatch.setattr(pt, "LOCK_ACQUIRE_SECONDS", 0.15)  # keep the test fast

    capsys.readouterr()
    code = pt.main(["status", str(plan), "--id", "1.1", "--state", "wip"])
    err = capsys.readouterr().err
    assert code != 0, "a busy lock must refuse the write, not proceed without it"
    assert "held by another plan_tool process" in err
    assert "nothing was written" in err
    # the plan is untouched and the other holder's lock is left alone
    assert _marker(read(plan), "1.1") == "[]"
    assert lock.exists()


def test_busy_lock_blocks_every_mutating_command(pt, new_plan, capsys, monkeypatch):
    plan = new_plan("lk4")
    plan.with_suffix(".lock").write_text("1234 live", encoding="utf-8")
    monkeypatch.setattr(pt, "LOCK_ACQUIRE_SECONDS", 0.05)
    capsys.readouterr()
    assert pt.main(["meta", str(plan), "--field", "commits", "--value", "abc123"]) != 0
    assert pt.main(["amend", str(plan), "--summary", "s", "--detail", "d"]) != 0
    assert pt.main(["addphase", str(plan), "--tasks", "1"]) != 0
    assert "commits" not in pt.parse_meta(read(plan)).get("commits", "abc123")


def test_busy_lock_on_one_plan_blocks_a_two_plan_ref(pt, new_plan, capsys, monkeypatch):
    a = new_plan("lk5a")
    b = new_plan("lk5b")
    b.with_suffix(".lock").write_text("1234 live", encoding="utf-8")
    monkeypatch.setattr(pt, "LOCK_ACQUIRE_SECONDS", 0.05)
    capsys.readouterr()
    assert pt.main(["ref", "--this", str(a), "--other", str(b), "--type", "forward"]) != 0
    # neither side was linked, and a's lock was released on the way out
    assert "lk5b.html" not in pt.parse_meta(read(a)).get("forward-refs", "")
    assert not a.with_suffix(".lock").exists()


def test_acquire_deadline_outlasts_a_normal_write(pt):
    # the lock only helps if it waits out a real read-modify-write instead of
    # giving up after ~2s the way the old fail-open version did
    assert pt.LOCK_ACQUIRE_SECONDS >= 10
