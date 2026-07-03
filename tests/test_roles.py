"""`roles build`: structured manifest, mode/acceptance compilation, CODEOWNERS
identity behaviour, overlap refusal, and glob-engine agreement with the guard."""

import json


def _role_md(role, sot, code_glob, reports_to="architect", github=None,
             mode=None, acceptance=None):
    lines = ["---", f"role: {role}", f"reports_to: {reports_to}"]
    if github:
        lines.append(f'github: "{github}"')
    if mode:
        lines.append(f"mode: {mode}")
    if acceptance:
        lines.append(f"acceptance: {acceptance}")
    lines += [
        "owns:",
        "  source_of_truth:",
        f"    - {sot}",
        "  code:",
        f"    - {code_glob}",
        "  supporting:",
        f"    - docs/{role}/**",
        "---",
        "",
        f"# Role: {role}",
        "",
    ]
    return "\n".join(lines)


def _roles_dir(tmp_path, roles):
    """roles: name -> dict of _role_md kwargs (sot, code_glob required)."""
    d = tmp_path / "roles"
    d.mkdir()
    for name, kw in roles.items():
        (d / f"{name}.md").write_text(_role_md(name, **kw), encoding="utf-8")
    return d


def _build(pt, rd, co):
    return pt.main(["roles", "build", "--dir", str(rd), "--codeowners", str(co)])


def test_roles_build_structured_manifest(pt, tmp_path):
    rd = _roles_dir(tmp_path, {
        "ux": {"sot": "specs/ux-*.html", "code_glob": "src/ui/**", "github": "@org/ux"},
        "engineer-api": {"sot": "specs/api-*.html", "code_glob": "src/api/**",
                         "github": "@org/api"},
    })
    co = tmp_path / "CODEOWNERS"
    assert _build(pt, rd, co) == 0
    manifest = json.loads((rd / "_roles.json").read_text(encoding="utf-8"))
    # top-level project knobs (defaults) + structured per-role owns
    assert manifest["mode"] == "track"
    assert manifest["acceptance"] == "manual"
    ux = manifest["roles"]["ux"]
    assert ux["source_of_truth"] == ["specs/ux-*.html"]
    assert ux["code"] == ["src/ui/**"]
    assert ux["supporting"] == ["docs/ux/**"]
    assert ux["github"] == "@org/ux"
    assert "src/ui/**" in ux["owns"] and "docs/ux/**" in ux["owns"]  # union for CODEOWNERS


def test_roles_build_mode_acceptance_from_architect(pt, tmp_path):
    rd = _roles_dir(tmp_path, {
        "architect": {"sot": "specs/vision-*.html", "code_glob": "docs/architecture/**",
                      "mode": "protect", "acceptance": "auto", "github": "@org/arch"},
        "engineer-api": {"sot": "specs/api-*.html", "code_glob": "src/api/**",
                         "github": "@org/api"},
    })
    co = tmp_path / "CODEOWNERS"
    assert _build(pt, rd, co) == 0
    manifest = json.loads((rd / "_roles.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "protect"
    assert manifest["acceptance"] == "auto"


def test_codeowners_uses_github_identity(pt, tmp_path):
    rd = _roles_dir(tmp_path, {
        "engineer-api": {"sot": "specs/api-*.html", "code_glob": "src/api/**",
                         "github": "@acme/api-team"},
    })
    co = tmp_path / "CODEOWNERS"
    assert _build(pt, rd, co) == 0
    text = co.read_text(encoding="utf-8")
    assert "src/api/  @acme/api-team" in text
    assert "@engineer-api" not in text  # never a bare role slug


def test_codeowners_comments_out_unmapped_role(pt, tmp_path, capsys):
    rd = _roles_dir(tmp_path, {
        "engineer-api": {"sot": "specs/api-*.html", "code_glob": "src/api/**"},  # no github
    })
    co = tmp_path / "CODEOWNERS"
    capsys.readouterr()
    assert _build(pt, rd, co) == 0
    out = capsys.readouterr().out
    text = co.read_text(encoding="utf-8")
    # commented out, with the explanatory trailer, and a build warning
    assert "# no github identity mapped for role engineer-api" in text
    assert "no github identity mapped for role 'engineer-api'" in out
    assert "@engineer-api" not in text


def test_roles_build_is_byte_identical(pt, tmp_path):
    rd = _roles_dir(tmp_path, {
        "ux": {"sot": "specs/ux-*.html", "code_glob": "src/ui/**", "github": "@o/ux"},
        "engineer-api": {"sot": "specs/api-*.html", "code_glob": "src/api/**", "github": "@o/api"},
    })
    co = tmp_path / "CODEOWNERS"
    _build(pt, rd, co)
    j1 = (rd / "_roles.json").read_bytes()
    c1 = co.read_bytes()
    _build(pt, rd, co)
    assert (rd / "_roles.json").read_bytes() == j1
    assert co.read_bytes() == c1


def test_roles_build_overlap_refused(pt, tmp_path, capsys):
    rd = _roles_dir(tmp_path, {
        "engineer-core": {"sot": "specs/core-*.html", "code_glob": "src/**"},
        "engineer-api": {"sot": "specs/api-*.html", "code_glob": "src/api/**"},
    })
    co = tmp_path / "CODEOWNERS"
    capsys.readouterr()
    code = _build(pt, rd, co)
    out = capsys.readouterr().out
    assert code != 0
    assert "overlapping" in out
    assert "engineer-core" in out and "engineer-api" in out
    assert not (rd / "_roles.json").exists()  # nothing generated on failure


def test_supporting_overlap_is_allowed(pt, tmp_path):
    # supporting globs may overlap across roles (logging/attribution only); build passes.
    rd = tmp_path / "roles"
    rd.mkdir()
    (rd / "a.md").write_text(_role_md("a", "specs/a-*.html", "src/a/**") .replace(
        "docs/a/**", "docs/shared/**"), encoding="utf-8")
    (rd / "b.md").write_text(_role_md("b", "specs/b-*.html", "src/b/**").replace(
        "docs/b/**", "docs/shared/**"), encoding="utf-8")
    co = tmp_path / "CODEOWNERS"
    assert _build(pt, rd, co) == 0


def test_glob_engine_agreement(pt):
    # The ONE matcher the guard and disjointness both use: ** spans dirs, * within a
    # segment. Overlap is expressed purely through glob_match.
    assert pt.glob_match("src/api/handler.py", "src/api/**")
    assert not pt.glob_match("src/apix/handler.py", "src/api/**")
    assert pt.glob_match("specs/api-streaks.html", "specs/api-*.html")
    assert not pt.glob_match("specs/api/streaks.html", "specs/api-*.html")  # * no cross '/'
    # a nested-** owner overlaps a broader owner of the same subtree
    assert pt.glob_overlap("src/**", "src/api/**")
    assert not pt.glob_overlap("src/api/**", "src/web/**")
    assert pt.glob_overlap("docs/**", "docs/api/contract.md")
