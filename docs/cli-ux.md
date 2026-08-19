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
  `--campaign` additionally records the run as an exploration campaign under the
  attributed problem (opt-in; the research state files are unchanged either way).
- `opentorus prove PROBLEM-XXXX` — one budgeted proof session on a dossier
  (literature → draft → gap-fill).
- `opentorus campaign start PROBLEM-XXXX` — a persistent, resumable portfolio
  campaign on a dossier: several distinct branches, a scored scheduler,
  failed-attempt memory, obligations closed only against accepted artifacts, an
  append-only event log. See [campaign-engine.md](campaign-engine.md).

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
| Research | `research [--campaign]`, `journal …`, `review run/list/resolve/gate` |
| Campaigns | `campaign start/resume/status/pause/stop/list/verify/tree/dashboard/import-research` |
| Theorem-level literature | `theorem extract/list/show/link/check/review/coverage` |
| Integrity | `problem referee [--apply-downgrades] [--json]`, `check-algebra` |
| Execution | `env list/verify/pin` |
| Authoring | `problem report/export`, `paper compile`, `pack export/reproduce/notebook` |
| Sessions | `replay last/session`, `export`, `import` |
| Governance & cost | `usage`, `governance budget/scan`, `dashboard`, `doctor [--capabilities] [--probe] [--json]` |
| Evaluation | `eval run`, `eval digest [PATH…] [--json]`, `eval record` |

### `campaign …` — two statuses, always labelled

```bash
opentorus campaign start PROBLEM-0001 --mode prove-or-refute --branches 4 --max-steps 40
opentorus campaign status CAMPAIGN-0001 [--json]
opentorus campaign pause CAMPAIGN-0001 --reason "..."   # resumes at the phase it left
opentorus campaign resume CAMPAIGN-0001                  # idempotent on a finished one
opentorus campaign stop CAMPAIGN-0001 --reason "..."    # terminal; --reason required
opentorus campaign list [--problem PROBLEM-0001] [--json]
opentorus campaign verify CAMPAIGN-0001 [--json]         # replay the log vs snapshot.json; re-check every recorded closure
opentorus campaign tree CAMPAIGN-0001 [--plain|--json|--dot] [--kind K] [--status S] [--depth N] [--out FILE]
opentorus campaign dashboard CAMPAIGN-0001 [--live] [--plain|--json|--dot]   # needs opentorus[dashboard]
opentorus campaign import-research "question" | --slug SLUG [--problem P] [--force]
```

`start` prints the campaign id on its own line first, then the summary. Every
campaign command that reports state prints **two** statuses and labels them: the
*campaign status* (orchestration — phase, budget, branches, work items) and the
*problem status*, derived from accepted dossier artifacts exactly as
`opentorus problem verdict` derives it. A completed campaign does not mean the
problem is solved, and the CLI says so on `status`, `list`, `stop` and in the
group help. Campaign ids are workspace-unique, so no command needs the problem id.
`--json` emits the same records the text view renders.

### `theorem …` — candidates until a human accepts them

```bash
opentorus theorem extract PAPER-0001 [--problem PROBLEM-0001] [--llm]
opentorus theorem list [--problem P] [--paper PAPER-0001] [--status candidate|accepted|rejected] [--json]
opentorus theorem show THMREF-0001 [--json]
opentorus theorem link THMREF-0002 THMREF-0001 --relation implies [--rationale "..."]
opentorus theorem check THMREF-0001 --problem PROBLEM-0001 --claim CLAIM-0003 [--json]
opentorus theorem review THMREF-0001 --status accepted --note "..." [--category C] [--root-relation R] [--problem P]
opentorus theorem coverage PROBLEM-0001 [--mode M] [--record] [--json] | --set CATEGORY LEVEL --evidence PAPER-0001
```

Extraction (heuristic or `--llm`) yields `candidate` references only; `theorem
review --status accepted` is the sole path to `accepted`, and only accepted
references license "it is known that" language in reports. `theorem check`
exits `2` when the deterministic applicability check comes out `rejected`. See
[theorem-references.md](theorem-references.md).

### `doctor` — profiles, routes, backends

`opentorus doctor` now also reports the model **profiles** (provider/model,
credential env-var *name* and whether it is set), the **routes** per task class
(unknown profile names fail the check), missing **credentials** (names only),
**formal-systems**, **dashboard** (whether the `dashboard` extra is installed),
**paper-parsing**, **dossier-state** (dossiers, campaigns and their replay
diagnostics, `problems/` writable) and **version**. `--capabilities` adds the
per-profile capability tables and whether each route has a fallback; `--probe`
(implies `--capabilities`) probes every non-mock profile online for tool calling
(one model call each) and caches the result in
`.opentorus/providers/capabilities.json`; `--json` emits every check as
`{name, ok, detail, data}`. Absent optional backends are reported as ok and
informational — the exit code is `1` only for a failed check. See
[model-routing.md](model-routing.md).

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

### The report: one design, two renderings

`problem export --pdf` typesets the dossier with the bundled `opentorus.cls`
(`opentorus/research/dossier/templates/`), a self-contained document class re-copied
into the workspace on every compile, so template fixes reach dossiers built by an
older OpenTorus. When no TeX toolchain — or no model — is available, the export falls
back to a standalone HTML report instead of failing.

Both renderings draw from the **same design system**, so the fallback reads as the
same document rather than as a plain-text dump:

| | PDF | HTML |
|---|---|---|
| palette | `\definecolor` in `opentorus.cls` | CSS vars from `dossier/theme.py` |
| status colour | `status_chip()` | `.chip-*` classes |
| both from | `theme.STATUS_KIND` | `theme.STATUS_KIND` |

`theme.py` is the single source for the palette and the status→colour rule; the class
repeats the hex values because LaTeX cannot import Python, and
`tests/test_html_export.py` pins the two copies together so they cannot drift.

Every optional package in `opentorus.cls` is probed with `\IfFileExists` first, so a
minimal TeX installation still produces a PDF; it just gets a plainer one (no
Libertinus text/math fonts, no tinted boxes). The HTML inlines its stylesheet — the
report is a local file, and MathJax is its only external fetch. What the class
provides:

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

Two conventions carry epistemic weight rather than being decorative, and both hold in
either rendering:

- **Chip colour tracks what the artifacts license.** Green is reserved for
  `verified` / `formally_verified` / `supported` / `succeeded`; open and in-flight
  statuses are amber, negative outcomes red, and anything unrecognised — including
  `unverified` — stays neutral grey. Colour must never upgrade a claim.
- **Caveats get a box, not a buried sentence.** The "sketches are not verified
  proofs" and "a counterexample candidate is not a refutation" notes are `otcaution`
  blocks, so a reader skimming the report cannot miss them.

`otoutput` is a distinct environment because the retired `preprint.cls` loaded
`lineno`, which pinned the stock `verbatim` such that `fvextra`'s `breaklines` never
fired and long stdout ran off the page. `opentorus.cls` does not load `lineno`, so
plain `verbatim` now wraps too; the generator, the sanitiser and the compose prompt
still use `otoutput` as the canonical name.

## Output conventions

- Tables and panels are rendered with [`rich`](https://github.com/Textualize/rich);
  structured output (manifests, ledgers) is plain JSONL/YAML on disk so it can be
  diffed and scripted.
- **Exit codes**: `0` on success, non-zero on failure. Quality gates
  (`opentorus check`) and verification commands exit non-zero when they fail, so
  they compose in CI. The integrity checks follow this too: `check-algebra` exits
  `2` when it rejects a claim (e.g. a false interior optimum), and `problem
  referee` exits `2` on a `block` verdict. The convention is `1` = error, `2` = a
  gating verdict or a refused request, `130` = interrupted:
  - `campaign start` exits `2` for an unknown `--mode`, `--branches < 2` in
    prove-or-refute, a negative budget, no positive budget on any axis after
    merging config and flags, or prove-or-refute with `--no-primary-claim` and no
    designated primary claim (the remediation is printed); `campaign
    import-research` exits `2` when the run was already imported (use `--force`);
    `campaign verify` exits `1` on a replay mismatch or on a recorded obligation
    closure the current settlement rules no longer accept; `campaign resume` on a
    completed or stopped campaign exits `0` with a note; Ctrl-C during `start` /
    `resume` pauses the campaign (reason `interrupted`) and exits `130`.
  - `theorem check` exits `2` when the applicability result is `rejected`;
    `doctor` exits `1` when any check fails.
- **Errors are structured**: a failed shell command prints the command, exit
  code, a short stderr summary, the likely cause, and a suggested next action.
- **Honest reporting**: when a capability is unavailable (no container runtime,
  missing optional dependency, unreachable provider), OpenTorus says so rather
  than silently degrading or pretending success.

## Help conventions

Every group and command answers `--help`; sub-commands are listed alphabetically.
A group whose commands report state that could be misread says so in its help
text — `campaign --help` states that campaign status is orchestration and that
the problem status comes from `opentorus problem verdict`; `theorem --help` states
that extraction yields candidates and only `theorem review` accepts. Flags that
mean "unlimited" say `0 = unlimited`; flags that cannot be written by `config
set` (mappings such as `models.profiles`, `task_routes`) are documented in
`config.yaml` itself and by `doctor`.

## Confirmations and modes

Effecting actions are gated by the permission policy. In `ask` mode the CLI
prompts inline (allow-once / session-allow); restricted claim upgrades require an
explicit confirmation. `--mode review` makes the whole session read-only. See
[safety.md](safety.md).

## Desktop notifications

Long runs ping the desktop (native toast via `notify-send` / `osascript` /
PowerShell, terminal bell as fallback) when a turn finishes or an approval is
blocking the loop. By default only background or piped runs notify
(`ui.notify_only_unfocused`); turn-complete toasts need `ui.notify_min_elapsed_seconds`
of wall-clock first. The text is reduced to plain prose before it is sent —
Markdown headings, list markers, emphasis and link targets stripped, the first
paragraph kept, cut at a word boundary — and escaped for the daemon's markup, so a
`<` or `&` in a model answer cannot mangle the toast.

```
OpenTorus finished in 2m 14s
Task: Prove the Crouzeix conjecture for 3×3 matrices
The conjecture holds for the tested family; see PROOF-0003.
```

```
OpenTorus needs your approval
Action: pytest tests/ -q
Command requires confirmation in ask mode. (risk: medium)
Approve in the terminal to continue.
```

The approval toast is sent with *critical* urgency so it stays on screen (on
desktops that honour the hint) until the prompt is answered; the finished toast
is *normal*. All of this is configurable under `ui:` in `config.yaml`
(`notifications_enabled`, `notify_on_turn_complete`, `notify_on_permission`).
