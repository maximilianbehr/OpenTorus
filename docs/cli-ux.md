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
| Evaluation | `eval run`, `eval digest [PATH…] [--json]`, `eval record` |

### `eval digest` — what a finished run actually did

`opentorus eval digest [PATH…]` reads a finished workspace and reports counts and
patterns: the tool-call histogram, repeated failures with their error text, the longest
run of consecutive searches, verifier outcomes split into accepted / rejected /
inconclusive, claim statuses, experiment outcomes, and the prompt-to-completion token
split. `--json` emits the same record for scripting; several paths can be passed at once
to compare runs.

A digest is deliberately *descriptive*. Its flags name patterns that have marked stuck
runs before — a search loop, a proof written but never submitted to a verifier, a run
where every experiment failed — and nothing in it judges whether the mathematics was
right. That judgement stays with the artifacts, the referee, and the honesty linter.

### Recording verification evidence

`FORMAL_PROOF` and `VALIDATED_NUMERICAL` are the only verification-grade evidence types:
they are what lets a claim leave `supported`. Both must cite an accepted verifier run,
so `problem evidence` requires the artifact:

```bash
opentorus proof submit --backend coq --claim CLAIM-0001 --file proof.v   # → PROOF-0003
opentorus problem evidence --claim CLAIM-0001 --type FORMAL_PROOF --artifact PROOF-0003
```

A missing, rejected, or inconclusive attempt is refused with the reason. If nothing was
machine-checked, record support-only evidence (`EXPERIMENT`, `COMPUTATION`,
`PROOF_SKETCH`) instead — that is honest, and it keeps the claim at `supported`.

### The report PDF

`problem export --pdf` typesets the dossier with the bundled `preprint.cls`
(third-party, BSD-2) plus `opentorus.sty`, the OpenTorus design layer. Both live in
`opentorus/research/dossier/templates/` and are re-copied into the workspace on every
compile, so template fixes reach dossiers built by an older OpenTorus. `preprint.cls`
is vendored verbatim and must stay that way — the house style belongs in
`opentorus.sty`.

Every optional package in `opentorus.sty` is probed with `\IfFileExists` first, so a
minimal TeX installation still produces a PDF; it just gets a plainer one (no
Libertinus text/math fonts, no tinted boxes). What the style provides:

| Macro / environment | Use |
|---|---|
| `\artifact{EXP-0001}` | any local artifact id |
| `\statusok` / `\statuswarn` / `\statusbad` / `\statusbadge` | status chips |
| `\gapmarker{[GAP-1]}` | a gap marker in a proof sketch |
| `otoutput` | captured program output — **use instead of `verbatim`** |
| `\otruncmd{...}` | the command line an experiment ran |
| `otcaution` / `otpanel` | epistemic caveat box / neutral panel |
| `\othead`, `\ottype`, column types `L` and `P{...}` | booktabs + tabularx tables |
| `\otdossierpanel`, `\otmeta` | the metadata strip under the title |
| `\otartifactindex{...}` | the closing artifact roll-up |

Two conventions carry epistemic weight rather than being decorative:

- **Chip colour tracks what the artifacts license.** Green is reserved for
  `verified` / `formally_verified` / `supported` / `succeeded`; open and in-flight
  statuses are amber, negative outcomes red, and anything unrecognised — including
  `unverified` — stays neutral grey. Colour must never upgrade a claim.
- **Caveats get a box, not a buried sentence.** The "sketches are not verified
  proofs" and "a counterexample candidate is not a refutation" notes are `otcaution`
  blocks, so a reader skimming the PDF cannot miss them.

`otoutput` exists because `preprint.cls` loads `lineno`, which pins the stock
`verbatim` in a way that defeats `fvextra`'s `breaklines` — long stdout then runs off
the page. The generator and the LaTeX sanitiser both rewrite `verbatim` blocks to
`otoutput`, and the compose prompt tells the model to emit it directly.

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
