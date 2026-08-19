# The campaign dashboard

`opentorus campaign dashboard CAMPAIGN-0001` opens a read-only terminal view of
one campaign's proof tree: the campaign's orchestration state on top, the tree
on the left, the selected node's detail on the right, and a diagnostics panel
whenever the graph carries validation issues. It shows exactly the graph
`campaign tree` prints (`opentorus.campaign.proof_tree`), through the same
read-only builder, and adds navigation, expand/collapse, filters, search and an
optional live refresh.

The dashboard is optional and lives in `opentorus.dashboard`; the base install
does not depend on it (see [Installing](#installing)).

```
+---------------------------------------------------------------------------+
| Campaign CAMPAIGN-0001 on PROBLEM-0001  mode=prove-or-refute              |
|   campaign status=completed  phase=completed                              |
| Problem status (derived from dossier artifacts): HEURISTIC_ONLY / ...      |
|   Problem status is derived from dossier artifacts (status_gate + scope); |
|   no node status and no campaign state ever upgrades it.                  |
| budget: steps 3 / 50, tokens 0 / unlimited, ...  branches: completed=3 .. |
+------------------------------------+--------------------------------------+
| - o ROOT [equivalent] root: ...    | o OBL-0001  obligation  status=open  |
|   - o BRANCH-0001 [equivalent] ... | statement: Justify the induction step|
|       o OBL-0001 [equivalent] ...  | root relation: equivalent -- can     |
|   + o BRANCH-0003 [supporting] ... |   settle the root                    |
|     x BRANCH-0004 [equivalent] ... |   condition: needs_justified_equiv.. |
|   - o CLAIM-0001 [equivalent] ...  | parents: BRANCH-0001                 |
|       o EVID-0001 [supporting] ... | closure_modes: nl_proof_referee_.. . |
|       o PROOF-0001 [equivalent] .. | campaign provenance: branch_id=...   |
+------------------------------------+--------------------------------------+
| Graph issues: [error] missing_ref: ...            (only when there are any)|
+---------------------------------------------------------------------------+
| kind=all  status=all  live=off                                            |
| j/k or arrows: move  enter: expand/collapse  f: kind filter  s: status .. |
+---------------------------------------------------------------------------+
```

(The real screen uses the tree's glyphs -- check, circle, cross, flag, subset
-- named in `campaign tree`'s legend; they are spelled out here to keep this
file ASCII.)

## Installing

```
pip install 'opentorus[dashboard]'      # adds textual
opentorus doctor                        # the "dashboard" check says whether it is installed
```

Without the extra, `opentorus campaign dashboard ID` exits 1 with

```
The dashboard needs the optional 'dashboard' extra: pip install 'opentorus[dashboard]'
```

and everything else -- `campaign tree`, `campaign status`, and the dashboard
command's own `--plain` / `--json` / `--dot` exports -- keeps working. Importing
`opentorus.cli`, `opentorus.campaign` or `opentorus.dashboard` never imports
`textual` (a test and the wheel-install CI step assert this); only
`opentorus.dashboard.app` and `opentorus.dashboard.widgets` do, and
`run_dashboard` imports them lazily.

## What it shows

**Header** (`OverviewModel`, from `campaign.status.summarize_snapshot`): the
campaign id, problem id, mode, phase and *campaign status*, the pause / stop /
failure / completion reason when there is one, the budget ledger per axis
(steps, tokens, cost, wall; `0` limit = unlimited), branch counts by status,
open / closed obligations, rounds and artifact count, the running worker (work
item, role, branch), the last routing decision (task class, profile, provider,
actual model), campaign-log diagnostics, graph issue counts and the last few
events.

The header also prints the **problem status**, on its own line, labelled
`derived from dossier artifacts`. It is `proof_tree.settlement.root_status`
(`status_gate.derive_status` + `scope.classify_outcome`) and is recomputed on
every load from the dossier's claims, evidence, proofs and verifications.
Campaign status and problem status are two different things and the dashboard
never lets one stand in for the other: a `completed` campaign next to an
`UNSOLVED` problem is the normal case.

**Tree** (`TreeRowModel`, from `proof_tree.render.tree_rows`): one line per
visible node, indented by depth, with the status glyph (`symbol_for`), the node
id, its relation to the root in brackets, its kind, a short title and its own
ledger status. Nodes with children carry `-` (expanded) or `+` (collapsed). A
node reached twice (diamonds, cycles) shows once more as `-> ID (shown above)`
instead of a second subtree, so a cyclic graph renders completely.

**Detail** (`NodeDetailModel`): the statement or objective, assumptions,
quantifiers (obligations), the root relation with what settling this node could
mean for the root (`settlement.relation_settlement`: `can settle the root` /
`cannot settle the root`, the condition and the reason), the status and its
source ledger, parents, children, dependencies, supporting / contradicting
artifacts, verification refs, review findings, kind-specific fields (closure
modes, gap count, backend, evidence type, ...), in/out edges, campaign
provenance (branch, work item, role, sequence), the branch's cost (steps,
tokens, USD, wall) and work items, routing provenance (decision id -> profile
/ provider / actual model, resolved from `.opentorus/usage/routing.jsonl` when
readable), created/updated timestamps and every validation issue that names the
node.

**Diagnostics panel**: shown only when `ProofGraph.issues` is non-empty; errors
first, capped at a dozen lines with a pointer to `campaign tree` for the rest.

**Status bar**: the active kind/status filter, the search text, whether live
refresh is on, the key hints, and the last notice (`reloaded`, `reload failed:
...`, `no open obligation in the current view`).

## Keys

| key | action |
|---|---|
| `j` / `k`, arrows | move the cursor down / up |
| `enter` | expand / collapse the node under the cursor (leaves do nothing) |
| `f` | cycle the kind filter: all, then each node kind present in the graph |
| `s` | cycle the status filter: all, then each status present (open, in_progress, closed, verified, contradicted, suspended, ... first, the rest sorted) |
| `/` | open the search box; type, `enter` applies (id, title, statement, bare artifact id; case-insensitive), `esc` cancels |
| `esc` | clear an applied search |
| `g` | jump to `ROOT` |
| `o` | jump to the next open / in-progress obligation after the cursor (wraps) |
| `r` | reload: re-read the campaign files, the dossier and the ledgers |
| `l` | toggle live refresh (re-read every `--refresh` seconds, default 2) |
| `q` | quit |

Filters keep the root and the ancestors of every match, so the tree stays
connected (`render.filter_graph`); a search keeps the ancestors of every hit and
ignores collapse state while it is active, so a hit is never hidden under a
collapsed parent. The kind and status cycles offer only the values that occur in
the current graph -- cycling through empty views is noise. All of these are pure
functions in `opentorus.dashboard.adapters` (`build_rows`, `next_open_obligation`,
`ViewState`) and are tested without a terminal.

## Read-only guarantee

The dashboard writes nothing: no campaign event, no `snapshot.json`, no usage
record, no dossier change. Its loader (`adapters.load_dashboard_data`) uses the
same read paths as `campaign status` and `campaign tree` --
`store.open_campaign(...).load()`, `status.summarize_snapshot`,
`proof_tree.builder.build_proof_graph`, `providers.pool.read_routing_ledger` --
and the package never names a writer (a test scans `src/opentorus/dashboard/`
for `CampaignStore`, `write_snapshot`, `record_usage`, `append_jsonl`,
`atomic_write_text` and file writes; another drives the app headlessly with
`CampaignStore.append`, `CampaignStore.write_snapshot` and `usage.record_usage`
monkeypatched to raise, and compares file mtimes before and after).

Because it only reads, the dashboard can be left open next to a running
campaign (`--live`) or another terminal issuing `campaign resume` / `pause`;
it will pick the changes up on the next refresh.

## Non-interactive exports

```
opentorus campaign dashboard CAMPAIGN-0001 --plain    # the indented text tree
opentorus campaign dashboard CAMPAIGN-0001 --json     # ProofGraph as JSON
opentorus campaign dashboard CAMPAIGN-0001 --dot      # Graphviz digraph
```

These render through `opentorus.campaign.proof_tree.render` without importing
`textual` (so they work on a base install) and produce byte-identical output to
`campaign tree --plain/--json/--dot`. Use `campaign tree` for `--kind`,
`--status`, `--depth` and `--out`.

Exit codes: 0 ok; 1 unknown campaign, unreadable workspace, missing extra, or
more than one export flag.

## Malformed graphs

The builder never raises on bad input: an unreadable ledger, a corrupt line, a
dangling reference, a cycle, an obligation closed without a closing artifact --
each becomes a `ValidationIssue` on the graph (see `docs/proof-tree.md`,
"Validation"). The dashboard shows them three ways: the header counts them
(`graph issues: missing_ref=1, cycle=1 (2 error(s), 0 warning(s))`), the
diagnostics panel lists them, and each node's detail lists the issues that name
it. Rows still render: a cycle appears as a repeat marker, an unattached node
appears after the root's subtree, a dangling dependency stays in the node's
`depends on:` line with a `missing_ref` issue next to it. If a reload fails
outright (the workspace disappeared, the campaign directory is unreadable) the
last good data stays on screen and the status bar says `reload failed: ...`.

A campaign started with `--no-run` (no branches yet) shows the root alone; the
kind and status cycles then offer only `all`.

## Node status never upgrades the problem status

Every node's `status` is a copy of what its ledger says (a claim's `claims.jsonl`
status, an obligation's event-log status, a verifier run's accepted/rejected).
The dashboard cannot change any of them, and none of them feed the problem
status line: that is derived from dossier artifacts by `status_gate` and
`scope` on every load. A closed obligation, a completed branch, a search that
shows only verified nodes, or a completed campaign leaves the problem status
exactly where the dossier's accepted artifacts put it. Special-case and
relaxation nodes carry the subset glyph and their detail says `cannot settle the
root`, so a proof of a special case is never read as the root being settled.
