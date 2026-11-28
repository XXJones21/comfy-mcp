# comfy-mcp `canvas` branch: work summary

Context for another project. What this fork branch adds, why, and where it stands.
Fork: `XXJones21/comfy-mcp`, branch **`canvas`** (head `9355232` at the time of writing).
It is a test branch, not for upstream as it is. Companion repo:
`XXJones21/comfyui-canvas-bridge`, 0.3.2 (see its `WORK_SUMMARY.md`).

## What it adds

Six MCP tools that let an agent work on the workflow open in a ComfyUI window. They
call the Canvas Bridge node pack, which must be installed in that ComfyUI.

| Tool | What it does |
|---|---|
| `canvas_snapshot` | The live canvas as text: nodes with refs (`n12`, `g3`), wires, widgets, boxes, and warnings. `scope`: all, viewport, selection, `group:g3`, or a list of refs. |
| `canvas_layout` | Tidies all or part of the graph. The bridge checks the result against quality targets and refuses a change that makes it worse (`force=True` overrides). If only notes are out of place, it moves just the notes (`mode: "notes_only"`). |
| `canvas_act` | A batch of edits, one undo step each, shown by the agent cursor: move, align, connect, disconnect, set, add, delete, group, ungroup, fit, title. `capture_each` saves a PNG after each op. |
| `canvas_move` | One move: `x`/`y` (box top-left), `cx`/`cy` (box centre), or `right_of`/`below` another ref. |
| `canvas_capture` | A PNG of the graph plus a JSON sidecar. The image also comes back inline (long edge at most 1568 px), so the agent can look at it without reading a file. `inline=False` turns that off. |
| `canvas_focus` | Pans and zooms the view to a scope; never changes the graph. |

The intended loop for an agent: `canvas_snapshot` → `canvas_act` (a batch of moves) →
`canvas_capture` → look → adjust → repeat. Or use `canvas_layout` for a one-shot tidy.

## How it works

- `src/comfy_mcp/canvas.py` (leaf module) POSTs to `/canvas_bridge/<op>` on the
  targeted ComfyUI, with stdlib `urllib` only.
- The target is resolved like the other tools:
  1. `COMFYUI_URL` / `COMFYUI_HOST`
  2. Comfy Desktop's port lock
  3. `127.0.0.1:8188`
- Each call sends:
  - `actor`: `agent:claude:<pid>`, or `COMFY_MCP_ACTOR` if set, so two agents show as
    two cursors
  - `client`: the comfy-mcp version and install commit
- Each reply includes:
  - `comfy_mcp`: for example `comfy-mcp 0.11.0 @9355232`
  - `bridge`: the node pack's version
  - `comfyui`: the base URL

  A stale install is easy to spot from these.
- Timeouts:
  - The bridge's relay timeout is sent in the body; the HTTP wait is 10 s longer.
  - `capture`: 60 s.
  - `act`: scales with the number of ops (at most 600 s).

## Rule exception

AGENTS.md says every tool is a `comfy --json` passthrough and that this server has no
HTTP client. This branch adds a **temporary test exception**, written into AGENTS.md:

- The `canvas_*` tools (and only they) may call `/canvas_bridge/*`, from `canvas.py`
  only, with stdlib `urllib` only.
- It lasts until comfy-cli ships `comfy canvas` commands. Then these tools become
  `_run_comfy` passthroughs and `canvas.py` goes away.

## Commits on `canvas` (oldest first)

1. `42abf76` docs(agents): temporary test exception for the canvas tools
2. `e34836a` canvas_snapshot / layout / capture / focus over the bridge route
3. `025f5da` docstring trim, README tool count, payload budget
4. `33ffe14` canvas_layout `force` flag for the bridge's no-regression guard
5. `d054077` each op credited to a per-process agent actor
6. `390830b` canvas_act and canvas_move
7. `a27625e` comfy-mcp version and install commit in every result
8. `9355232` capture returns the image inline; move takes a centre point

## Tests

- `tests/test_canvas.py`: request shapes, timeouts, errors, actor and client fields,
  act/move ops, the inline image, and cx/cy.
- `tests/test_tool_annotations.py`: rows for the six tools.
- `tests/test_payload_budget.py`: the budget was raised to 17,150 tokens for the new
  tool descriptions.
- `pytest -q`: all canvas tests pass. On Windows the full suite has 19 failures that
  were already there before this branch.
- `ruff check` and `ruff format --check` are clean.

## Using it (Claude Code plugin)

A local marketplace, `comfy-canvas-marketplace` (plugin `comfy-canvas`), runs:

    uvx --from git+https://github.com/XXJones21/comfy-mcp@canvas comfy-mcp

`uvx` caches the branch, and a stale cache makes new tools look missing. After new
commits, run `uv cache clean comfy-mcp` and restart Claude Code. Or pin the plugin to a
commit (`@<sha>`).

To check which copy is running, read the `comfy_mcp` field of any canvas result.

## Open questions and next steps

- Move these tools behind comfy-cli (`comfy canvas …`) so the HTTP exception can go.
- Shared presence with comfy-multi-player, ideally as a ComfyUI core feature, so humans
  and agents see each other on the same channel.
- Layout gaps (bridge side): a long row of stages is never wrapped onto two lines, and
  Markdown notes do not render in captures.
