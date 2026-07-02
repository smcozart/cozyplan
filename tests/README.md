# planf3 regression suite

Regression tests for `scripts/plan_tool.py` and the two hooks
(`scripts/hooks/guard_plan_edit.py`, `scripts/hooks/lint_plan.py`).

## Running

From the repo root:

```
uv run --with pytest pytest tests/ -q
```

No `pyproject.toml` is required — `plan_tool` is stdlib-only and is loaded in-process
via `importlib`. The hooks are stdin/stdout protocols, so they are exercised as
subprocesses; the lint-hook tests additionally require `uv` on PATH (the hook shells
out to `uv run plan_tool validate`).

## Layout

- `conftest.py` — loads `plan_tool` as a module, `new_plan` scaffold fixture, hook runner.
- `test_new.py` / `test_status.py` / `test_meta.py` — core mutating commands.
- `test_ref_amend_report.py` — references, amendments, report-back events.
- `test_validate.py` — token severity by status, schema-ceiling refusal.
- `test_index.py` / `test_roles.py` / `test_rollup.py` — deterministic generated artifacts.
- `test_guard_hook.py` / `test_lint_hook.py` — the PreToolUse / PostToolUse hooks.

All artifacts are written under pytest's `tmp_path`; the repo's own `specs/` and
`roles/` are never touched.
