"""Plan write lock: sequential ops release cleanly; a stale lock is broken."""

import os
import re
import time


def _marker(text, sid):
    m = re.search(r'data-status-for="' + re.escape(sid) + r'"[^>]*>(\[[^\]]*\])', text)
    return m.group(1) if m else None


def test_sequential_ops_release_lock(pt, new_plan):
    plan = new_plan("lk")
    assert pt.main(["status", str(plan), "--id", "1.1", "--state", "wip"]) == 0
    assert pt.main(["status", str(plan), "--id", "1.2", "--state", "x"]) == 0
    # lock file is always cleaned up in the finally/release path
    assert not plan.with_suffix(".lock").exists()


def test_stale_lock_is_broken(pt, new_plan, capsys):
    from conftest import read
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
