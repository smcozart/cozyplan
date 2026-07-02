"""`new`: deterministic scaffolding from templates/plan.html."""

from conftest import read, sidecar_events


def test_new_scaffold_validates_clean_with_placeholder_warning(pt, new_plan, capsys):
    plan = new_plan("scaffold-a", title="Scaffold A")
    capsys.readouterr()  # drain scaffold output
    code = pt.main(["validate", str(plan)])
    out = capsys.readouterr().out
    assert code == 0
    assert "OK" in out
    # Fresh scaffold keeps free-form {{}} tokens; a draft plan reports them as a warning.
    assert "warn:" in out
    assert "placeholder token" in out


def test_new_stamps_metadata(pt, new_plan):
    plan = new_plan("scaffold-meta", title="Meta Plan", owner="engineer-api")
    text = read(plan)
    meta = pt.parse_meta(text)
    assert meta["id"] == "scaffold-meta"
    assert meta["status"] == "draft"
    assert meta["schema"] == "1"
    assert meta["owner"] == "engineer-api"
    assert meta["created"]  # non-empty ISO stamp


def test_new_has_all_anchors(pt, new_plan):
    text = read(new_plan("scaffold-anchors"))
    assert 'data-meta="id"' in text
    assert 'data-meta="status"' in text
    assert 'data-phase="1"' in text
    assert 'data-status-for="phase-1"' in text
    assert 'data-status-for="1.1"' in text
    assert 'data-status-for="1.2"' in text
    assert 'data-status-for="g.1"' in text  # global validation id
    assert "data-amendments-list" in text


def test_new_refuses_overwrite(pt, new_plan, specs, capsys):
    new_plan("dupe", title="First")
    capsys.readouterr()
    code = pt.main(["new", "dupe", "--title", "Second", "--specs", str(specs)])
    err = capsys.readouterr().err
    assert code != 0
    assert "already exists" in err


def test_new_rejects_non_kebab_name(pt, specs, capsys):
    code = pt.main(["new", "Not_Kebab", "--title", "X", "--specs", str(specs)])
    assert code != 0
    assert "kebab-case" in capsys.readouterr().err


def test_new_writes_created_event(new_plan):
    plan = new_plan("scaffold-event", title="Event Plan", owner="ux")
    events = sidecar_events(plan)
    assert len(events) == 1
    ev = events[0]
    assert ev["event"] == "created"
    assert ev["details"]["id"] == "scaffold-event"
    assert ev["details"]["owner"] == "ux"
    assert ev["details"]["file"] == "scaffold-event.html"
