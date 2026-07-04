"""`ref` (bidirectional back/forward links) and `amend` (newest-at-bottom)."""

from conftest import read, sidecar_events


def test_ref_is_bidirectional(pt, new_plan):
    a = new_plan("ref-a", title="A")
    b = new_plan("ref-b", title="B")
    code = pt.main(["ref", "--this", str(a), "--other", str(b), "--dir", "back"])
    assert code == 0
    ma = pt.parse_meta(read(a))
    mb = pt.parse_meta(read(b))
    # this=back -> a gains a back-ref to b; b gains the reciprocal forward-ref to a
    assert "ref-b.html" in ma["back-refs"]
    assert "ref-a.html" in mb["forward-refs"]


def test_ref_no_duplicate_on_rerun(pt, new_plan):
    a = new_plan("ref-c", title="C")
    b = new_plan("ref-d", title="D")
    for _ in range(2):
        pt.main(["ref", "--this", str(a), "--other", str(b), "--dir", "forward"])
    assert pt.split_list(pt.parse_meta(read(a))["forward-refs"]) == ["ref-d.html"]
    assert pt.split_list(pt.parse_meta(read(b))["back-refs"]) == ["ref-c.html"]


def test_ref_logs_events_on_both_plans(pt, new_plan):
    a = new_plan("ref-e", title="E")
    b = new_plan("ref-f", title="F")
    pt.main(["ref", "--this", str(a), "--other", str(b), "--dir", "back"])
    assert any(e["event"] == "ref" for e in sidecar_events(a))
    assert any(e["event"] == "ref" for e in sidecar_events(b))


def test_amend_appends_newest_at_bottom(pt, new_plan):
    plan = new_plan("amend-order")
    pt.main(["amend", str(plan), "--summary", "first change", "--detail", "d1"])
    pt.main(["amend", str(plan), "--summary", "second change", "--detail", "d2"])
    text = read(plan)
    assert text.index("first change") < text.index("second change")
    # both inserted inside the amendments container
    body = text.split("data-amendments-list")[1]
    assert "first change" in body and "second change" in body
