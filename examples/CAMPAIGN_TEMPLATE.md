# Campaign dossier template (general-conjecture scope policy)

How to build a campaign example under the scope policy: the primary target is
always the **full quantified conjecture**; fixed instances are internal tools.
Both driver script and `notes.md` follow the skeletons below. Used by the
initial campaign (Frankl, Graceful Tree, Barnette, Caccetta–Häggkvist, Lonely
Runner, Sidorenko) and every future general-conjecture example.

## Non-negotiables

1. **Fresh status audit, dated.** On creation day, run a *fresh web search* for
   the conjecture's status — never from memory (Brouwer and Sendov both changed
   status in 2026 and would have been mis-scoped). Record the audit date and
   findings in `notes.md`. Partial results are classified **with sources**
   (they become `KNOWN_RESULT`s / typed claims), never blanket-stamped "open".
   A resolved or claimed-resolved conjecture goes to `calibration-*`, not the
   open campaign.
2. **General target, checked.** The statement must classify as `general` under
   `dossier.scope.classify_target` (unbounded quantifier / universal
   structure). The driver runs `opentorus problem verdict` at the end; a
   `fixed_instance` warning is a template violation.
3. **Deterministic primary-claim designation.** The *driver* (not the model)
   creates the primary claim and designates it:

   ```bash
   opentorus problem claim "${TARGET}" --type CONJECTURE \
     --statement "<the full quantified statement, verbatim>"
   opentorus problem verdict "${TARGET}" --set-primary CLAIM-0001
   ```

   Only through this designation are `GENERAL_CONJECTURE_PROVED` /
   `_REFUTED` ever derivable — and only from verification artifacts.
4. **Dual research process** in the task text (see skeleton): a refutation
   track and a proof track that exchange information. Failed counterexample
   searches may suggest lemmas; they are never proof evidence.
5. **Machine-checking bias.** Wherever a step reduces to a finite check, the
   task text routes it through `proof_submit` (sympy/interval/SMT/Coq), not
   `exp_run`. The anchoring chain (workflow step 7b → gap-fill hint →
   completion-window nudge) reinforces this at run time.
6. **Campaign gate (mandatory in drivers).** Set
   `opentorus config set agent.prove_require_instance_work true`. Both smoke
   runs showed that statement prose alone — including an imperative START-HERE
   block — never starts the instance program: models follow what a gate
   enforces, not what prose requests (the literature phase works precisely
   because it is tool-gated). The gate holds the clean completion until at
   least one experiment or one `proof_submit` is recorded, delivers an explicit
   instruction at the recovery surface, and ends the run honestly via the
   no-progress window if the model still cannot comply — it forces the
   *attempt*, never the outcome, and the derived verdict stays with the
   artifacts.
7. **Four-eyes audit review.** Every status audit is counter-checked by a
   *second, independent session* (fresh web search, every cited id resolved
   against its abstract, every "settled class" statement compared with what the
   source actually proves) **before** the dossier's `KNOWN_RESULT`s are treated
   as anchors. Empirical basis: the first counter-audit of three template
   dossiers found six real errors — a missed frontier paper (Lonely Runner
   11–13, arXiv:2604.23906, published 3.5 months before the audit), two
   misattributed citations, one mis-cited source that was already being
   `paper add`-ed into the dossier, one overstated theorem, and one wrong graph
   name. Audit errors are baked into every later report; the counter-audit is
   the cheapest place to catch them. Corrections are marked
   `amended <date>` in the audit block, never silently overwritten.

## `notes.md` skeleton

```markdown
# Problem: <Conjecture name>

**Primary target (general).** <Full quantified statement. This exact text is
also the driver-created primary claim.>

**Status audit (<YYYY-MM-DD>).** Fresh literature/web check at creation:
<status; claimed proofs with review state; sources with arXiv ids>.

**Known partial results (classified, with sources).**
- <result> — <source> (becomes a KNOWN_RESULT / THEOREM-with-source, not "open")

**Refutation track.** Negate the conjecture: a counterexample is <exact
structure>. Generators: <problem-specific>. Search: <enumeration / SAT / SMT /
CP / heuristic + exact completion>. Minimize candidates; re-verify
independently; convert to exact witnesses and certify via proof_submit. A
verified counterexample claim must name the primary claim in depends_on.

**Proof track.** Reproduce the partial results above; minimal-counterexample
reductions; mine invariants from exact experiments; candidate lemmas tested
against generated examples, formalized via proof_submit when finite; assemble
the dependency graph; every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** <which finite instances/experiments
feed both tracks, and what each can and cannot show>.

**Claim policy.** Every conclusion is exactly one of: verified construction /
machine-checked theorem / exhaustive certified result / computational or
numerical evidence / conjecture / failed attempt. The campaign verdict is
derived by `opentorus problem verdict`; only GENERAL_CONJECTURE_PROVED or
GENERAL_CONJECTURE_REFUTED resolve the campaign.
```

## Driver skeleton (deltas from the existing examples)

Standard blocks (fresh workspace, model config with `timeout_seconds 2400`,
docker env, audit-verified `paper fetch` sources only — fetch downloads and parses the PDF so the campaign's literature branch has local text; `paper add` merely registers) plus, after `problem new`:

```bash
opentorus problem claim "${TARGET}" --type CONJECTURE --statement "<statement>"
opentorus problem verdict "${TARGET}" --set-primary CLAIM-0001
opentorus --verbose campaign start "${TARGET}" --mode prove-or-refute --branches 4 --max-steps 200
CAMPAIGN="$(opentorus campaign list --problem "${TARGET}" --json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)[-1]["campaign_id"])')"
opentorus campaign status "${CAMPAIGN}"; opentorus campaign tree "${CAMPAIGN}"
opentorus campaign verify "${CAMPAIGN}"        # replay the event log against the snapshot
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint
opentorus problem verdict "${TARGET}"          # scope check + terminal classification
opentorus problem export "${TARGET}" --pdf
```

## README skeleton

Problem + status-audit summary (dated), what the driver runs, the dual-track
framing, prerequisites, honesty note naming the *realistic* outcomes
(status sketch, certified partial results, NUMERICAL/COMPUTATIONAL_EVIDENCE —
not a resolution).
