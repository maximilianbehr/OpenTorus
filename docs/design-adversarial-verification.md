# Design note: adversarial review and branch-and-score verification

Status: **proposal — partially implemented.** Item 1 (neutral *prove or refute*
framing in `opentorus prove`) and item 3c (recorded dead ends fed back into the
prove prompt) shipped; the rest is open. Every item below is a
*harness* change: it adds ways for the loop to catch its own mistakes, and none of
them may promote a claim's status. The EVAL-001..008 invariants in
`tests/test_dossier.py` stay untouched; a new pass that only *finds* problems is
compatible with them by construction, a new pass that *settles* anything is not.

## Context

The techniques here are the transferable half of the "AI-assisted research
playbook" distilled in *Accelerating Scientific Research with Gemini: Case Studies
and Common Techniques* (arXiv:2602.03837, Feb 2026): iterative self-correction for
review, neutral prompting against confirmation bias, neuro-symbolic
propose→evaluate→prune loops with numeric ground truth, negative prompting to force
alternative routes, and explicit dependency enumeration. OpenTorus already has the
skeleton for most of them — deterministic referee, `[GAP-n]` discipline, verbatim
error feedback, `FailedAttempt` records — but several are one-directional or never
fed back into the model's context. What follows maps each technique to the code
that would carry it.

## 1. Neutral prove-or-refute framing — shipped

`build_prove_prompt` (`agent/prove_loop.py`) used to ask for "the strongest proof
or proof sketch you can"; refutation existed only as `--disprove`. The default goal
is now "prove or refute — do not assume it is true", step 4 asks which cited results
suggest the statement could be *false*, step 5 runs a bounded sanity check before a
direction is chosen (a counterexample → `COUNTEREXAMPLE_CANDIDATE` + refutation
sketch; a pass is corroboration only), and the open-problem status sketch asks for
both routes and the crux blocking each. `--disprove` now only changes priority.
Pinned by `test_build_prove_prompt_default_is_neutral_prove_or_refute`.

Not done, and worth a follow-up: a *statement-fidelity* referee finding. The paper's
§7.1 reports the model "conveniently reinterpreting" a question (an existential bound
delivered for a worst-case ask). `referee.py` classifies claims but does not compare
the primary proof's `theorem` against the dossier statement; a cheap deterministic
check (quantifier words, "for all"/"there exists", parameter names) plus a `revise`
finding would cover the common case.

## 2. Multi-round LLM referee (findings only)

`dossier/referee.py:referee_review` is deterministic on purpose: it can lint, count,
and cross-check artifacts, but it cannot see that a *definition* demands perfect
consistency while the *construction* only delivers statistical consistency — the
class of bug the paper's SNARG case study found with an LLM reviewer run under a
strict protocol. `prompts/referee.md` exists but is narration-only today.

Proposal — `opentorus problem referee --llm` (and an opt-in pass at the end of
`prove`):

1. **Initial review** of the primary `PROOF-*` body plus the claims it cites, told
   to be strictly objective and to report only errors and gaps.
2. **Self-critique**: re-read its own review; for every reported error, either
   quote the exact line that is wrong and say why, or withdraw it as unverified.
3. **Revised review** incorporating the withdrawals.
4. **Second self-critique** with an explicit coverage question ("which lemmas,
   appendices, and cited PAPER-* notes did you not read?").
5. **Final review**, structured as `Complete Proof` (no open findings) or
   `Structured Partial Progress` with each gap tagged.

Output: `REFEREE-*` artifact carrying LLM findings marked `origin=llm`, severity
`revise` at most by default (a `blocking` LLM finding requires the deterministic
referee to corroborate it — otherwise an LLM hallucination could stall a run
forever). Blocking-and-corroborated findings reopen `[REFEREE]` gaps through the
existing `reopen_referee_gaps`. Nothing here changes a claim status.

The same five-step protocol pointed at a parsed `PAPER-*` artifact gives a
*paper-review* mode (`opentorus paper referee PAPER-XXXX`), which the paper's §9.4
argues is the coming bottleneck. Output there is a note artifact, not a claim.

Cost control: five LLM turns per pass, so gate it behind `agent.referee_llm_rounds`
(default 0) and count it against the run's token/cost budget like any other phase.

## 3. Branch-and-score for symbolic candidates, obstruction feedback

The paper's cosmic-strings loop: the model proposes an intermediate closed form in
LaTeX *and* a Python evaluator for it, the harness scores it against a high-precision
baseline, tracebacks and instability are fed back verbatim, and >80% of ~600
branches are pruned automatically. After a route succeeds, negative prompting ("do
not use this method; reflect and pick a different plan") produced six independent
routes.

What OpenTorus has: eight flat strategy templates (`dossier/strategies.py`),
`FailedAttempt` records with `reusable_obstruction` (`dossier/models.py`), interval
certificates as the only `VALIDATED_NUMERICAL` path, and negative prompting for
*tool* failures only (`agent/compaction.py`, `agent/loop.py`). Missing:

- **`symbolic_candidate` experiment template.** Inputs: the claimed expression, a
  generated evaluator, a baseline (mpmath high-precision quadrature or an existing
  `EXP-*`), tolerance. The runner scores agreement, records the traceback on
  failure, and writes `NUMERICAL_EVIDENCE` at best — a match is corroboration, a
  mismatch is a recorded refutation of that candidate. Interval certificates remain
  the only route to `VALIDATED_NUMERICAL` (invariant 1).
- **Branch records.** `ApproachRecord` gains optional `parent_id`, `score`,
  `pruned_reason`. `problem tree` renders them; the report lists pruned branches
  under failed attempts (invariant 5 already wants them first-class).
- **Obstruction feedback into prompts — shipped.** `known_dead_ends()` in
  `agent/prove_loop.py` gathers `known_obstructions`, the `FailedAttempt` ledger
  (reusable first) and dossier-attributed `failed_attempts` memory; the proof
  prompt and the gap-recovery hint carry it as "Known dead ends for this dossier —
  do NOT retry these unchanged", and the workflow asks the model to log failed
  routes tagged with the dossier id. Not applied to the research loop: its
  experiment selection is deterministic and its single narration turn steers
  nothing, so there is no prompt there for a constraint to act on. Follow-up worth
  doing: a `failed_attempt_add` tool so the model can write the dossier ledger
  (with `reusable_obstruction`) directly instead of only workspace memory.
- **Route diversity on success.** After a primary proof closes (or a candidate is
  confirmed), one optional bounded pass with the closed route named as forbidden;
  the result is an `exploration`-scope sketch, never a second primary.

## 4. Smaller follow-ups

- **Dependency enumeration** (paper §2.5): a gap-fill step "list every external
  theorem this proof uses"; each becomes a `REFERENCE_FACT` that must cite a local
  `PAPER-*` or degrades to `[GAP-n]`. Mechanizes invariant 3 instead of relying on
  the citation rules in the prompt.
- **Context de-identification** (§2.7, §9.2): opt-in `prove --deidentify` strips the
  problem's name and paper context from the *attack* prompt while the honesty
  labelling at record time is unchanged. Note the tension with
  `statement_suggests_open_problem`, which today downgrades the goal to a status
  sketch — attempting and labelling are separable, and the paper's evidence is that
  models go conservative once told a problem is open.
- **`cross_domain_map` strategy** (§2.2): "theorems from other fields with the same
  shape"; candidates must resolve to local sources through `lit_search`/kb.
- **Stronger-model verification pass** (§6.1): after gap-fill, route one verify-and-
  simplify turn to a larger model via governance model routing.
- **Calibration dossiers** from the paper's refuted conjectures and the SNARG flaw:
  known answers, so a run either finds the crux or measurably does not.

## Order of work

4a (dependency enumeration) is, like the shipped 3c, a prompt-plus-test change
with no schema impact — do it next. Then 2 (LLM referee, findings only),
which needs a config knob and one new artifact field. 3a/3b (symbolic candidates,
branch records) touch `models.py` and the report and should ship as one reviewed
step with EVAL tests extended for the new experiment type.
