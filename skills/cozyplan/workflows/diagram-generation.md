# Diagram Generation

Fill or update the embedded visuals in a plan `.html` file. Every visual is a **simple, professional Excalidraw diagram** — boxes, arrows, and short labels that map out the idea — authored as an editable `.excalidraw` source file and rendered to a PNG **locally, with no API key**. Pick the sub-workflow based on the incoming `USER_PROMPT`:

| Sub-workflow | When to call it |
| --- | --- |
| Create | The prompt asks to generate, fill, or add the plan's diagrams from scratch (empty `{{...IMAGE` slots) |
| Update | The prompt asks to change, refine, regenerate, or replace diagrams that already exist in the plan |

## Tooling

Diagrams are produced with the globally-installed **`excalidraw-diagram`** skill — invoke it via the Skill tool (no OpenAI key, no network image API). That skill authors the `.excalidraw` JSON and renders it to PNG through a local headless Chromium pipeline:

```bash
cd ~/.claude/skills/excalidraw-diagram-skill/references && uv run python render_excalidraw.py <path-to-file.excalidraw>
```

The render writes a `.png` next to the `.excalidraw` file. The `.excalidraw` source is the editable artifact — the user can open and tweak it in the **Excalidraw VS Code extension** (`pomdtr.excalidraw-editor`), then re-render.

## Shared rules for every diagram

- Keep it **simple and straightforward**: one or two core ideas per diagram, boxes + arrows + short labels. Default to the `excalidraw-diagram` skill's Simple/Conceptual mode, not the comprehensive/evidence-artifact mode.
- Keep total words shown under ~10. No paragraphs inside the diagram.
- Match the plan's synced visual identity: pull diagram colors from the plan's `:root` palette (the same hex values used in the HTML `<style>` block) so the rendered PNG sits naturally on the page. Use `roughness: 0` for clean, modern edges and `opacity: 100`.
- Render wide where it fits the section (landscape composition reads best embedded in the plan).
- Save both the `.excalidraw` source and the rendered `.png` to `IMAGES_OUTPUT_DIR` (create it if missing). Name files after their slot, e.g. `hero.excalidraw` / `hero.png`, `phase-1.excalidraw` / `phase-1.png`.

## Create

1. **Find slots** — Grep the plan for `{{...IMAGE` placeholders (hero, problem, solution, per-phase, questionables, notes). Each comment names the intended subject.
2. **Design each diagram** — For each slot, decide the one or two ideas it must convey and the visual pattern (flow, fan-out, convergence, timeline, before/after) that mirrors it. Keep it minimal.
3. **Author + render** — Invoke the `excalidraw-diagram` skill to build the `.excalidraw` file in `IMAGES_OUTPUT_DIR` using the plan's palette, then render it to PNG with `render_excalidraw.py`. Read the rendered PNG and fix layout (clipping, overlap, spacing) until it looks clean.
4. **Embed** — Replace each `<!-- {{...IMAGE: ...}} -->` placeholder with `<img src="<plan-name>/<file>.png" alt="...">`, keeping the existing `<figure>`/`<figcaption>`.
5. **Report** — List the diagrams generated (both `.excalidraw` source and `.png`) and the slots filled.

## Update

1. **Identify targets** — From the `USER_PROMPT`, determine which embedded diagrams to change.
2. **Edit the source** — Open the existing `.excalidraw` file in `IMAGES_OUTPUT_DIR` and edit the JSON to make the requested change (keep it simple, keep the palette). This is also where the user's manual VS Code edits live, so respect any changes already present.
3. **Re-render** — Run `render_excalidraw.py` on the edited `.excalidraw` to overwrite the PNG. Read the PNG and iterate until correct.
4. **Verify embed** — Confirm the `<img>` still points at the updated PNG; update `src`/`alt`/`<figcaption>` if the change warrants it.
5. **Report** — List the diagrams updated and what changed.
