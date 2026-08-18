# The proof tree

`opentorus campaign tree CAMPAIGN-0001` shows one campaign's *semantic proof
tree*: the campaign's orchestration nodes (branches, obligations, failure
signatures, campaign-proposed nodes) merged with the dossier's artifacts (claims,
evidence, proof attempts, experiments, failed attempts, reviews, theorem
references) and the workspace verifier ledger. The tree lives in
`opentorus.campaign.proof_tree` and is a **derived, read-only view**: it is
rebuilt on every call from the campaign snapshot and the ledgers, it persists
nothing, and it decides nothing.

Two rules hold everywhere in this layer:

* A node's `status` is a *copy* of what the owning ledger says (a claim's
  `claims.jsonl` status, an obligation's event-log status, a verifier run's
  accept/reject). The tree never writes a status back.
* The problem's status is derived from dossier artifacts by
  `research.dossier.status_gate.derive_status` and `research.dossier.scope.classify_outcome`
  and printed once at the top of the tree. No node status, no closed obligation,
  no finished branch and no completed campaign ever enters that derivation.

```
   campaign snapshot ----+
   (branches, obligations,|                        +---------------------+
    failure signatures,   +--> proof_tree.builder --> ProofGraph           |
    campaign nodes)       |    (read-only merge)     |  nodes, edges,      |
   dossier ledgers -------+                          |  issues, root_status|
   (claims, evidence,     |                          +---------+-----------+
    proofs, experiments,  |                                    |
    referee, THM refs)    |         proof_tree.validation <----+----> proof_tree.render
   workspace ledgers -----+         (ten issue codes)               (plain / json / dot)
   (proofs.jsonl, reviews,
    THMREF references)
```

## Node kinds

| kind | source | id | status vocabulary |
|---|---|---|---|
| `root` | dossier statement | `ROOT` | the derived report status (`UNSOLVED`, `HEURISTIC_ONLY`, ...) |
| `branch` | campaign snapshot | `BRANCH-NNNN` | `proposed`, `rejected`, `active`, `suspended`, `exhausted`, `completed` |
| `obligation` | campaign snapshot | `OBL-NNNN` | `open`, `in_progress`, `closed`, `contradicted`, `abandoned` |
| `claim` / `lemma` / `counterexample` | dossier `claims.jsonl` (`LEMMA_ATTEMPT` -> lemma, `COUNTEREXAMPLE_*` -> counterexample) | `CLAIM-NNNN` | the dossier claim statuses (`unverified` ... `formally_verified`) |
| `evidence` | dossier `evidence/index.jsonl` | `EVID-NNNN` | the direction: `supports`, `contradicts`, `neutral` |
| `proof-attempt` | dossier `proof_attempts/index.jsonl` | `PROOF-NNNN` | `sketch`, `in_progress`, `blocked`, `abandoned`, `verified` |
| `verification` | workspace `proofs.jsonl` (verifier runs) | `PROOF-NNNN@verifier` | `accepted`, `rejected`, `inconclusive` |
| `experiment` | dossier + workspace experiments (merged view) | `EXP-NNNN` | `planned`, `running`, `succeeded`, `failed`, `inconclusive` |
| `failed-attempt` | dossier `failed_attempts.jsonl`; campaign failure signatures | `FAILED-NNNN`, `FSIG-NNNN` | `failed`; the signature's error category |
| `review` | `reviews/index.jsonl` (targets in the tree); the latest referee report | `REVIEW-NNNN`, `REFEREE-NNNN` | the verdict (`pass`, `revise`, `block`, ...) |
| `theorem-reference` | `.opentorus/theorems/references.jsonl` (attributed to the problem); legacy dossier `THM-` refs | `THMREF-NNNN`, `THM-NNNN` | `candidate`, `accepted`, `rejected`; `legacy` |
| `work-item` | reserved (work items are folded into their branch's `extra`) | - | - |

Node ids reuse artifact ids, with one documented exception: the dossier's proof
attempts and the workspace verifier ledger share the `PROOF-NNNN` id space (the
collision `research/verifiers/proofs.py` describes), so verifier-ledger nodes are
`PROOF-NNNN@verifier`; `extra.artifact_id` keeps the bare id, and `search`
finds both.

Every node carries `root_relation` (how it relates to the root problem, see
below), `assumption_context`, `parents`, `dependencies`,
`supporting_artifacts` / `contradicting_artifacts`, `verification_refs`,
`review_findings`, timestamps, `source` (`campaign` / `dossier` / `workspace`)
and a kind-specific `extra` (routing decision ids, cost and work items for a
branch; gap count and scope for a proof attempt; closure information for an
obligation; campaign provenance -- branch, work item, campaign node -- for any
artifact a campaign produced).

## Edges

| relation | meaning | typical source -> target |
|---|---|---|
| `parent` | containment for display | branch -> root or parent branch; obligation -> branch; evidence -> its claim; proof attempt -> its first linked claim; review -> its target; artifact -> the branch that produced it |
| `depends_on` | logical dependency | claim -> claim (`depends_on`); obligation -> the proof its gap came from; evidence -> the experiment it reads |
| `supports` / `contradicts` | evidence direction; cited artifacts of an obligation | evidence -> claim; sketch -> claim; artifact -> obligation |
| `verifies` | a verifier run backs something | `PROOF-NNNN@verifier` -> proof attempt (`verification_artifact`), -> `FORMAL_PROOF` / `VALIDATED_NUMERICAL` evidence, -> the claim it was submitted for |
| `reviews` | a review/referee report is about a node | review -> target; referee -> root |
| `specializes` / `relaxes` | the branch's root relation | special-case branch -> parent; relaxation branch -> parent |
| `refutes` | a `COUNTEREXAMPLE_VERIFIED` claim against what it depends on | counterexample -> claim; -> root when the claim is the primary claim |
| `closes` | the artifact an `obligation_closed` event cited | verifier run / claim / proof attempt / theorem reference -> obligation |

Edges are resolved after every ledger has been read; a reference to something no
ledger holds becomes a `missing_ref` issue instead of an edge.

## Root relations and settlement

`RootRelation` (`campaign.models`) says how a branch or obligation relates to
the root problem. `proof_tree.settlement.RELATION_CAN_SETTLE` says whether
settling it can ever settle the root, and under which further condition:

| relation | can settle the root? | condition |
|---|---|---|
| `equivalent` | yes | `needs_justified_equivalence` -- the equivalence itself must be justified (verified reduction both ways, or an accepted reference) |
| `sufficient` | yes (proving direction only) | `needs_verified_reduction_and_obligations` -- the reduction is verified and every obligation it opens is closed |
| `necessary` | refuting direction only | `needs_converse` -- proving a necessary condition settles nothing without the converse |
| `counterexample-route` | yes (negatively) | `needs_accepted_witness` -- an accepted witness that passes every root assumption and violates the conclusion |
| `special-case` | never | a proof of a subclass leaves the general statement open |
| `relaxation` | never | a weaker statement neither proves nor refutes the stronger one |
| `supporting` | never | informs the attack, settles nothing itself |
| `unrelated` | never | - |
| `unknown` | never | classify the relation first |

`relation_settlement(relation)` returns a `SettlementVerdict{can_settle,
relation, condition, reason}`. In the plain view every node line shows its
relation in brackets and non-settling relations carry the subset glyph, so a
closed special-case obligation can never be read as the root being settled;
`special_case_root_closing` (below) makes the reverse an error.

## Obligation closure

`can_close_obligation(ot_dir, problem_id, obligation, *, artifact_id=None)` is
the **single source of truth** for closure. The verifier-coordinator worker
(`campaign/workers/verifier.py`) only turns an allowed verdict into a
`ClosureProposal`; the engine records `obligation_closed`; the reducer sets the
obligation's status. Nothing else closes an obligation, and closing one never
changes a claim status or the derived problem status.

Routes are tried in a fixed order and each requires an *accepted* artifact:

| closure mode | requires |
|---|---|
| `formal_proof`, `smt_certificate`, `exact_symbolic_certificate`, `validated_numerical_certificate` | a `PROOF-*` in the workspace verifier ledger, cited by the obligation, passing the four checks of `dossier.claims._require_verification_artifact` (exists, not inconclusive, accepted, recorded under this problem or unscoped) with a backend matching the mode; `formal_proof` accepts any accepted backend, the certificate modes need the matching one (`sympy` -> exact symbolic, `smt/z3/cvc5` -> SMT, `interval` -> validated numerical, `lean4/coq` -> formal). `source_proof_id` is never looked up in the ledger: it names a *dossier* sketch, and the two `PROOF-` id spaces collide. |
| `accepted_counterexample_certificate` | a cited dossier claim of type `COUNTEREXAMPLE_VERIFIED` (creatable only with an explicit verification record) whose record names every assumption the dossier records (`witness_satisfies_root_assumptions`: each `assumptions.yaml` statement or its `ASM-` id must occur in the claim's notes/statement, its cited artifacts, or the status-change reasons; a missing assumption refuses; a dossier without recorded assumptions passes vacuously). |
| `nl_proof_referee_accepted` | a *primary*-scope dossier proof attempt cited by the obligation whose `claim_links` name the obligation's claim (its `CLAIM-` dependencies, else the dossier's primary claim), with no open gaps (recorded gaps reconciled with the body's `[GAP-n]` markers), whose gap closure is documented (see below), and on which `referee_review(persist=False)` returns `pass` without classifying the claim as refuted. This is the weakest mode: it records that a hostile deterministic referee found nothing to object to in a gap-free sketch. It is not machine verification, and it never changes a claim status. |
| `accepted_literature_theorem` | a cited `THMREF-*` with `review_status == accepted` (only `theorem review` writes that) and an applicability check for this problem with `result == accepted` whose `target_id` is the obligation or its claim. |

Anything else stays open; `ClosureVerdict.details` lists every reason that was
checked, and the verifier-coordinator forwards them as notes.

### Deleting gap markers does not close obligations

An obligation created from a proof gap carries `gap_marker` (e.g. `GAP-1`) and
`source_proof_id`. Its status lives in the campaign event log; editing the proof
body cannot change it. Removing `[GAP-1]` from the body and clearing the recorded
gaps changes the proof node's `gap_count` (the tree shows that), and nothing
else: the obligation stays `open` until an `obligation_closed` event cites an
accepted artifact.

The referee route additionally requires the marker to be *accounted for*: the
body must still mention `[GAP-1]` in a closed context -- a `[GAP-1] closed: ...`
/ `handled` / `resolved` note, or a "Gaps closed" section -- exactly the closed
contexts `nl_proof.explicit_gaps` already recognises. A marker that simply
vanished is refused with a reason that says what to write instead
(`documented_gap_closure(body, "GAP-1")` returns `False`).

## Root status

`ProofGraph.root_status` is a `RootStatusView{label, rationale, report_status,
derived_from}` computed by `settlement.root_status`, which delegates to
`campaign.facts.root_math_status`: `label` is `scope.classify_outcome`'s
campaign-level classification, `report_status` is `status_gate.derive_status`'s
report rung, and `derived_from` names the two functions and the primary claim.
The `ROOT` node's status is `report_status`. Campaign completion, obligation
closure and branch status never enter it (`tests/test_settlement.py`
`test_campaign_completion_leaves_root_status_unchanged`). An unreadable dossier
yields `STATUS_UNCERTAIN` / `UNSOLVED` with the error as rationale -- never an
exception.

## Validation

`validation.validate_graph(graph)` returns typed `ValidationIssue{code,
node_ids, message, severity}` records and never raises (a check that fails on
strange input is itself reported as `malformed_node`). The builder attaches them
to `ProofGraph.issues`; the plain view prints them at the end.

| code | severity | meaning |
|---|---|---|
| `missing_ref` | error / warning | an edge, parent or dependency names an unknown node (error); a supporting/contradicting/verification artifact list names a tree-shaped id (`CLAIM-`, `EVID-`, `PROOF-`, ...) that is not in the tree (warning) -- ids the tree does not model (`PAPER-`, `APPR-`, `COV-`) are not flagged |
| `duplicate_id` | error | two node ids that differ only in case/whitespace; two records claiming one id at build time |
| `cycle` | error | a cycle over `parent` / `depends_on` edges (iterative DFS; each cycle reported once) |
| `self_dependency` | error | a node that is its own parent/dependency, or an edge to itself |
| `incompatible_assumptions` | error | a child assumes the negation of a parent assumption (`X` vs `not X` / `non-X`) |
| `invalid_relation` | error | a root relation outside the vocabulary; an edge relation outside the vocabulary; a relation the source/target kinds cannot carry (only a `review` may `reviews`, `closes` must target an obligation, ...) |
| `unsupported_transition` | error / warning | an obligation `closed` without a closing artifact; a status outside its ledger's vocabulary (error); a claim marked verified that no verification artifact reaches in the tree (warning) |
| `orphan_artifact` | warning | an artifact node with no edge at all |
| `special_case_root_closing` | error / warning | a special-case/relaxation node with a `closes` / `verifies` / `refutes` edge into the root, a status claiming the root is settled, or `extra.settles_root` (error); a closed special-case obligation attached directly to the root (warning) |
| `malformed_node` | error / warning | an unreadable ledger, a corrupt ledger line (reported with its line number), a missing root, an id/key mismatch, a failed check (error); a campaign node of a kind the tree cannot place (warning) |

## Exports

```
opentorus campaign tree CAMPAIGN-0001                # plain (default)
opentorus campaign tree CAMPAIGN-0001 --json         # ProofGraph as JSON (sorted keys)
opentorus campaign tree CAMPAIGN-0001 --dot          # Graphviz digraph
opentorus campaign tree CAMPAIGN-0001 --kind obligation --status open
opentorus campaign tree CAMPAIGN-0001 --depth 2 --out tree.txt
```

`--kind` / `--status` filter (repeatable); the root and the ancestors of every
matching node are kept so the tree stays connected. `--depth N` cuts the plain
view below depth N with a marker saying how many children are hidden. `--out`
writes the same text to a file (atomically). Exit 1 for an unknown campaign.

Plain:

```
Proof tree: PROBLEM-0001 (campaign CAMPAIGN-0001)
Problem status (derived from dossier artifacts): UNSOLVED / INCONCLUSIVE - claims or evidence exist but ...
Problem status is derived from dossier artifacts (status_gate + scope); no node status and no campaign state ever upgrades it.

o ROOT [equivalent] root: For every n >= 1, P(n) holds.  status=UNSOLVED
  o BRANCH-0001 [supporting] branch: Literature map  status=completed  (kind=literature steps=1)
  o CLAIM-0001 [equivalent] claim: CONJECTURE CLAIM-0001  status=unverified
    o EVID-0001 [unknown] evidence: PROOF_SKETCH evidence  status=supports  (type=PROOF_SKETCH)
    o PROOF-0001 [equivalent] proof-attempt: Induction sketch  status=sketch  (gaps=1 scope=primary)
  o BRANCH-0002 [equivalent] branch: Proof by induction  status=active  (kind=proof steps=6)
    o OBL-0001 [equivalent] obligation: Justify the induction step  status=open  (closable by nl_proof_referee_accepted, formal_proof)

Legend: <check> closed/verified/accepted  o open/in progress  x contradicted/refuted/rejected/failed  ? unknown  <subset> special-case/relaxation (cannot settle the root)  <flag> suspended/exhausted/blocked  [relation] = relation to the root
Issues: none
```

(The real output uses the glyphs named in the legend; they are spelled out here
to keep this file ASCII.)

JSON: `{"campaign_id", "problem_id", "root_id", "nodes": {id: ProofNode},
"edges": [ProofEdge], "issues": [ValidationIssue], "root_status":
RootStatusView, "generated_at"}` -- `ProofGraph.model_validate(json.loads(text))`
round-trips.

DOT: `digraph proof_tree { ... }` with one quoted, escaped node statement per
node (shape by kind: root `doubleoctagon`, branch `box`, obligation `hexagon`,
claim/lemma `ellipse`, counterexample `octagon`, evidence `note`, proof attempt
`component`, verification `diamond`, experiment `cylinder`, review
`parallelogram`, theorem reference `folder`), one labelled edge per relation,
and the derived problem status as the graph label.

The pure helpers `filter_graph`, `search_nodes`, `tree_rows` and `symbol_for` in
`proof_tree.render` are what the dashboard reuses; none of them touches a
ledger.
