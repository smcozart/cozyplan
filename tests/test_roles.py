"""`roles build`: manifest + CODEOWNERS generation, determinism, overlap refusal."""

import json


def _role_md(role, sot, code_glob, reports_to="architect"):
    return (
        "---\n"
        f"role: {role}\n"
        f"reports_to: {reports_to}\n"
        "owns:\n"
        "  source_of_truth:\n"
        f"    - {sot}\n"
        "  code:\n"
        f"    - {code_glob}\n"
        "  supporting:\n"
        f"    - docs/{role}/**\n"
        "---\n\n"
        f"# Role: {role}\n"
    )


def _roles_dir(tmp_path, roles):
    d = tmp_path / "roles"
    d.mkdir()
    for name, (sot, code_glob) in roles.items():
        (d / f"{name}.md").write_text(_role_md(name, sot, code_glob), encoding="utf-8")
    return d


def test_roles_build_disjoint(pt, tmp_path):
    rd = _roles_dir(tmp_path, {
        "ux": ("specs/ux-*.html", "src/ui/**"),
        "engineer-api": ("specs/api-*.html", "src/api/**"),
    })
    co = tmp_path / "CODEOWNERS"
    code = pt.main(["roles", "build", "--dir", str(rd), "--codeowners", str(co)])
    assert code == 0
    manifest = json.loads((rd / "_roles.json").read_text(encoding="utf-8"))
    assert set(manifest["roles"]) == {"ux", "engineer-api"}
    ux_owns = manifest["roles"]["ux"]["owns"]
    assert "src/ui/**" in ux_owns and "specs/ux-*.html" in ux_owns
    text = co.read_text(encoding="utf-8")
    assert "@ux" in text and "@engineer-api" in text
    assert "src/api/  @engineer-api" in text


def test_roles_build_is_byte_identical(pt, tmp_path):
    rd = _roles_dir(tmp_path, {
        "ux": ("specs/ux-*.html", "src/ui/**"),
        "engineer-api": ("specs/api-*.html", "src/api/**"),
    })
    co = tmp_path / "CODEOWNERS"
    pt.main(["roles", "build", "--dir", str(rd), "--codeowners", str(co)])
    j1 = (rd / "_roles.json").read_bytes()
    c1 = co.read_bytes()
    pt.main(["roles", "build", "--dir", str(rd), "--codeowners", str(co)])
    assert (rd / "_roles.json").read_bytes() == j1
    assert co.read_bytes() == c1


def test_roles_build_overlap_refused(pt, tmp_path, capsys):
    rd = _roles_dir(tmp_path, {
        "engineer-core": ("specs/core-*.html", "src/**"),
        "engineer-api": ("specs/api-*.html", "src/api/**"),
    })
    co = tmp_path / "CODEOWNERS"
    capsys.readouterr()
    code = pt.main(["roles", "build", "--dir", str(rd), "--codeowners", str(co)])
    out = capsys.readouterr().out
    assert code != 0
    assert "overlapping" in out
    assert "engineer-core" in out and "engineer-api" in out
    # nothing generated on failure
    assert not (rd / "_roles.json").exists()
