# CLI UX

OpenTorus is terminal-native. The command-line surface is the product, and it is
designed to be inspectable, scriptable, and honest.

## Invocation

```bash
opentorus --help        # top-level help
opentorus --version     # print version and exit
opentorus <group> --help  # help for any command group
python -m opentorus ...   # equivalent module invocation
```

Global flags work on every command:

- `--verbose` — informational logs **and streamed LLM request/response trace** during any
  LLM-backed command (`run`, `prove`, `problem extract`, `problem export`, …). Without it,
  interactive terminals show a spinner only (no chain-of-thought or streamed model text).
- `--debug` — verbose internals; full message bodies in the LLM trace.

## Entry points

- `opentorus` / `opentorus chat` — the interactive session (REPL) with slash
  commands (`/help`, `/mode review`, `/style <name>`, `/replay`, `/context`).
  The prompt supports persistent line editing: **TAB** completes slash commands
  and their arguments (e.g. `/model set provider <TAB>`), **↑/↓** recall previous
  inputs, **Ctrl+R** incrementally searches history, and `/history [n]` lists
  recent entries. History lives in `~/.opentorus/repl_history` (relocate with
  `$OPENTORUS_HISTORY_FILE`, disable with `$OPENTORUS_NO_HISTORY=1`).
- `opentorus tui` — a panelled terminal UI (plan, actions, patches, usage) over
  the same testable dispatch core.
- `opentorus run "<task>"` — run a single task (add `--plan --fresh` for a
  multi-step goal executed one step at a time with checkpoints). For which
  workflows fit `run` vs `--plan` vs `research`, see [examples/README.md](../examples/README.md).
- `opentorus research "<question>"` — the autonomous, budgeted research loop
  (counterexample/evidence over local papers — not a general survey solver).

## Extracting problems from papers and markdown

`opentorus problem extract <PAPER>` (alias `paper problems`) pulls numbered
open problems into **PROBLEM-* dossiers**. Markdown notes work too:

```bash
opentorus problem extract --from notes/workshop-problems.md
opentorus problem new --from-markdown notes/workshop-problems.md
```

It tries three methods for papers, in order:

1. **Heuristic** — copies verbatim `Problem X.Y` blocks from extracted text.
   `--heuristic-only` stops here.
2. **LLM** — drives extraction with the configured model. `--llm-only` skips
   the heuristic shortcut.
3. **Vision** — renders PDF pages to PNG for scanned or math-heavy PDFs.
   `--vision` forces this even when a text layer exists.

Markdown extraction defaults to the **LLM** path.

## Command surface (by area)

| Area | Commands |
|------|----------|
| Workspace | `init`, `status`, `config show/set`, `actions` |
| Coding | `diff`, `shell`, `check`, `patch …`, `checkpoint …` |
| Claims & evidence | `claim …`, `evidence …`, `graph …`, `explain <id>` |
| Experiments & proofs | `exp new/run/replay/summarize`, `proof submit/list` |
| Literature | `lit search/cite/link/gaps/doi`, `paper …` |
| Datasets & code | `data fetch/list/link`, `repo clone/test/list` |
| Knowledge & index | `index build/status/search`, `kb promote/query/stale` |
| Research | `research`, `journal …`, `review run/list/resolve/gate` |
| Integrity | `problem referee [--apply-downgrades] [--json]`, `check-algebra` |
| Execution | `env list/verify/pin` |
| Authoring | `problem report/export`, `paper compile`, `pack export/reproduce/notebook` |
| Sessions | `replay last/session`, `export`, `import` |
| Governance & cost | `usage`, `governance budget/scan`, `dashboard` |

## Output conventions

- Tables and panels are rendered with [`rich`](https://github.com/Textualize/rich);
  structured output (manifests, ledgers) is plain JSONL/YAML on disk so it can be
  diffed and scripted.
- **Exit codes**: `0` on success, non-zero on failure. Quality gates
  (`opentorus check`) and verification commands exit non-zero when they fail, so
  they compose in CI. The integrity checks follow this too: `check-algebra` exits
  `2` when it rejects a claim (e.g. a false interior optimum), and `problem
  referee` exits `2` on a `block` verdict.
- **Errors are structured**: a failed shell command prints the command, exit
  code, a short stderr summary, the likely cause, and a suggested next action.
- **Honest reporting**: when a capability is unavailable (no container runtime,
  missing optional dependency, unreachable provider), OpenTorus says so rather
  than silently degrading or pretending success.

## Confirmations and modes

Effecting actions are gated by the permission policy. In `ask` mode the CLI
prompts inline (allow-once / session-allow); restricted claim upgrades require an
explicit confirmation. `--mode review` makes the whole session read-only. See
[safety.md](safety.md).
