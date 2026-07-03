"""`checkpoint` / `accept` (git-native revert points) and verified-HEAD build-meta."""

from conftest import git, read, sidecar_events


def _new_committed(pt, git_repo, name):
    specs = git_repo / "specs"
    specs.mkdir(exist_ok=True)
    plan = specs / f"{name}.html"
    pt.main(["new", name, "--title", name.upper(), "--specs", str(specs)])
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-m", f"add {name}")
    return plan


def test_checkpoint_creates_tag_event_and_commit_meta(pt, git_repo):
    plan = _new_committed(pt, git_repo, "cp")
    assert pt.main(["checkpoint", str(plan), "--label", "phase 1 done"]) == 0
    evs = [e for e in sidecar_events(plan) if e["event"] == "checkpoint"]
    assert len(evs) == 1
    d = evs[0]["details"]
    assert d["tag"] == "planf3/cp/1"
    assert d["sha"] and d["tree"] and d["label"] == "phase 1 done"
    assert "planf3/cp/1" in git(git_repo, "tag", "--list").stdout
    assert d["sha"] in read(plan)  # sha appended to commits metadata


def test_checkpoint_refuses_dirty_tree(pt, git_repo, capsys):
    specs = git_repo / "specs"
    specs.mkdir(exist_ok=True)
    plan = specs / "cpd.html"
    pt.main(["new", "cpd", "--title", "X", "--specs", str(specs)])  # left uncommitted
    capsys.readouterr()
    code = pt.main(["checkpoint", str(plan)])
    err = capsys.readouterr().err
    assert code != 0
    assert "dirty" in err


def test_checkpoint_increments_tag_number(pt, git_repo):
    plan = _new_committed(pt, git_repo, "cpn")
    assert pt.main(["checkpoint", str(plan), "--label", "one"]) == 0
    git(git_repo, "commit", "-am", "cp meta 1")  # commit the metadata change
    assert pt.main(["checkpoint", str(plan), "--label", "two"]) == 0
    tags = git(git_repo, "tag", "--list").stdout
    assert "planf3/cpn/1" in tags and "planf3/cpn/2" in tags


def test_accept_records_event_and_checkpoints(pt, git_repo):
    plan = _new_committed(pt, git_repo, "acc")
    assert pt.main(["accept", str(plan), "--notes", "looks good"]) == 0
    evs = [e for e in sidecar_events(plan) if e["event"] == "accepted"]
    assert len(evs) == 1
    assert evs[0]["details"]["notes"] == "looks good"
    assert "planf3/acc/1" in git(git_repo, "tag", "--list").stdout


def test_build_meta_captures_verified_head(pt, git_repo):
    plan = _new_committed(pt, git_repo, "bm")
    head = git(git_repo, "rev-parse", "HEAD").stdout.strip()
    assert pt.main(["build-meta", str(plan)]) == 0
    evs = [e for e in sidecar_events(plan) if e["event"] == "build-meta"]
    assert evs[-1]["details"]["head"]["sha"] == head
    assert head in read(plan)  # verified sha appended to commits


def test_build_meta_rejects_nonexistent_commit(pt, git_repo, capsys):
    plan = _new_committed(pt, git_repo, "bmx")
    capsys.readouterr()
    code = pt.main(["build-meta", str(plan), "--commit", "deadbeefdeadbeef"])
    err = capsys.readouterr().err
    assert code != 0
    assert "does not exist" in err


def test_checkpoint_not_a_repo_errors(pt, new_plan, capsys):
    plan = new_plan("cp-norepo")  # tmp specs, not a git repo
    capsys.readouterr()
    code = pt.main(["checkpoint", str(plan)])
    err = capsys.readouterr().err
    assert code != 0
    assert "not a git repository" in err
