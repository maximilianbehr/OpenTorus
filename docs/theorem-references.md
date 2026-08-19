# Theorem references (THMREF)

The theorem-reference subsystem (`opentorus.research.theorems`) turns "PAPER-0003
says something about this" into a *located, reviewable* pointer to one numbered
result in a locally parsed paper, and builds two things on top of it:
deterministic **applicability checks** (does this theorem apply to this claim
under these assumptions?) and a category-based **literature coverage** map that
the campaign scheduler uses instead of a paper count.

Everything lives in the workspace, not in one dossier:

```
.opentorus/theorems/
  references.jsonl              TheoremReference   (THMREF-NNNN)
  relations.jsonl               TheoremRelation    (THMREL-NNNN)
  applicability_checks.jsonl    ApplicabilityCheck (THMAPP-NNNN)
  coverage/PROBLEM-XXXX.jsonl   assessments (COV-NNNN) + human overrides
```

A reference may carry `problem_id` (attribution) and `root_relation`, but the
same theorem is one artifact even when several problems cite it. The legacy
dossier `THM-*` refs (`problem theorem`) are untouched and still count as a
weak (partial) coverage signal.

## The rule that matters

```
   paper text ---extract---> candidate ---human review---> accepted
                 (heuristic or LLM)                        (theorem review)
                                    \---human review---> rejected
```

* Extraction never produces anything but `review_status="candidate"`, whatever
  the extracting model says.
* `store.set_review_status` (the `theorem review` command) is the only code path
  that writes `accepted`; `store.add_reference` refuses a reference born accepted.
* Only an **accepted** reference attributed to a problem makes
  `dossier.report.honesty_context(...)[1]` (`has_reference`) true, i.e. licenses
  "it is known that ..." language in reports. Candidates and rejected references
  never do. This is the single change to the honesty surface, pinned by
  `tests/test_theorem_honesty.py`.
* An applicability check that comes out `accepted` is a recorded, typed artifact.
  It never changes a claim status; promotion still needs a verification artifact
  exactly as described in `CONTRIBUTING.md`.

## Model

`TheoremReference` (schema_version 1, unknown fields tolerated):

| field | meaning |
|---|---|
| `id`, `paper_id`, `problem_id` | `THMREF-NNNN`; local `PAPER-XXXX` (must exist); optional attribution |
| `locator` | `SourceLocator{paper_id, page, section, label, source_path}` |
| `theorem_label`, `title` | "Theorem 2.1"; parenthesised name if any |
| `location_hash` | sha256 of the located source context (see below) |
| `excerpt` | quotation of the located context, at most 300 chars (validator) |
| `normalized_statement`, `assumptions`, `quantifiers`, `conclusion` | structured statement (heuristic or model-proposed) |
| `required_definitions`, `dependencies` | free text / other THMREF ids |
| `root_relation` | one of the campaign root relations (`equivalent`, `sufficient`, `necessary`, `special-case`, `relaxation`, `counterexample-route`, `supporting`, `unrelated`, `unknown`) or null |
| `categories` | coverage categories this reference covers |
| `extraction_method`, `extracting_model`, `routing_decision_id` | `manual` / `heuristic` / `llm`; the model that answered; the routing ledger id when a pool lease was used |
| `review_status`, `review_note` | `candidate` (default) / `accepted` / `rejected` |

`TheoremRelation{source_ref, target_ref, relation, provenance, rationale,
review_status}` with `relation` in `depends-on, implies, equivalent-to,
generalizes, specializes, contradicts, applies-to, requires-definition`.
`applies-to` may target a `CLAIM-` or `OBL-` id; every other target must be a
reference in the ledger.

`ApplicabilityCheck{theorem_reference_id, problem_id, target_id,
assumption_context, claim_text, direction, result, checks[], mismatches[],
performed_by, proposed_analysis, human_note}` with `result` in
`accepted | rejected | inconclusive | needs-human-review`.

`CoverageAssessment{id, problem_id, campaign_id, mode, entries{category ->
CoverageEntry{level, evidence_ids, provenance, note}}, critical_categories,
insufficient}`.

## Locators: what is checked, what is only warned

The paper cache has no page markers: `papers/PAPER-XXXX/text.txt` is the
page-joined full text, and `structure.json` is an outline (section title, first
page, first 280 chars). `locators.validate_locator` is honest about that:

| component | checked against | if it cannot be checked |
|---|---|---|
| `paper_id` | local paper artifact | error `unknown paper` (blocking) |
| `label` ("Theorem 2.1") | parsed corpus (`paper_citations.paper_corpus`) | corpus without any numbering -> warning; unparsed paper -> warning `unparsed` |
| `page` | `structure.json` `num_pages` (1..N) | no `structure.json` -> warning `page ... unverifiable` |
| `section` | section titles in `structure.json` | no outline -> warning |

Errors: unknown paper; a numbered result the corpus demonstrably lacks (or has
under another keyword: "Lemma 2.1" when the source only has "Theorem 2.1"); a
page beyond `num_pages`; a section title not in the outline. `ok` is false only
on errors; warnings mean "the cache cannot decide", never "invented".

`located_context(ot_dir, locator, width=400)` returns the statement text
starting at the label, cut at the next environment label / `Proof.` / heading,
whitespace-collapsed. It always searches the **full** corpus and prefers a hit
inside `text.txt` over the truncated outline previews, and a statement-like
occurrence (`Theorem 2.1.` / `Theorem 2.1 (`) over a citation in running text
("by Theorem 2.1 we get"). `location_hash(context)` is sha256 over that text.
Extraction and later checks use the same rule, so the hash is reproducible; a
re-parsed or replaced source shows up as `source text changed since extraction`.

`clip_excerpt(text, 300)` clips at a word boundary and appends `...`.

## Extraction (candidates only)

`extraction.extract_heuristic(ot_dir, paper_id, problem_id=None)` scans the
corpus for `Theorem|Lemma|Proposition|Corollary N` labels (each family+number
once), locates each, and fills the structured fields with shallow heuristics:
sentences opening with Let/Suppose/Assume/If -> `assumptions` (`If X, then Y`
is split), `for all/every/each`, `there exists/for some` -> `quantifiers`, text
after `then`/`we have`/`it follows` -> `conclusion`. Re-running is idempotent
(dedupe by paper + label). It raises when the paper is not parsed.

Every candidate (heuristic or LLM) also carries *category hints*
(`extraction.infer_categories(label, statement)`): `Lemma` / `Proposition` ->
`standard_tools_lemmas`; `Theorem` / `Corollary` -> `known_counterexamples` when
the statement names a counterexample, `known_negative_results` when it states a
non-existence or failure, else `strongest_known_positive_results`. The hint only
decides which coverage row the candidate appears in (at most `partial`); review
(`--category`) replaces it, and `adequate` still needs an accepted reference.

`extraction.extract_with_llm(ot_dir, paper_id, problem_id=None, pool=None,
provider=None, config=None)` asks a model (task class `theorem_extraction`
through the provider pool when available, else the given/configured provider)
for a JSON list of `{label, title, statement, assumptions, quantifiers,
conclusion, page, section}`. Every item is validated with `validate_locator`:
an item whose label the corpus lacks is dropped and logged; a real result whose
page/section fails validation is kept with that (model-invented) locator part
removed. Excerpt and hash always come from the local source, never from the
model's text; `extracting_model` and `routing_decision_id` are recorded; the
result is a candidate no matter what the model wrote.

## Relations

`relations.add_relation(ot_dir, src, dst, kind, provenance=..., rationale="",
review_status="candidate")` validates both ends and records provenance
(`manual|heuristic|llm`). `relation_graph` gives outgoing adjacency (rejected
edges excluded); `contradicting_refs(ot_dir, ref)` lists non-rejected
`contradicts` neighbours in either direction.

## Applicability checks

`applicability.check_applicability(ot_dir, ref_id, problem_id=..., assumption_context=[...],
claim_text=..., direction="forward"|"converse", target_id=None, proposed_analysis=None)`
runs these checks in order and records each as a `CheckItem{name, passed, detail}`:

| # | check | when it fails -> verdict |
|---|---|---|
| 1 | `reference_reviewed` (the reference's `review_status`) | `candidate` -> needs-human-review; `rejected` -> rejected |
| 2 | `paper_exists` | rejected |
| 3 | `locator_resolves` (`validate_locator.ok`) | rejected |
| 4 | `statement_observed` (context found and hash matches) | inconclusive (`source text changed since extraction`) |
| 5 | `hypotheses_represented` (reference has assumptions) | inconclusive |
| 6 | `context_implies_hypotheses` — evaluated **per hypothesis**: each one is a substring of / has token-Jaccard >= 0.6 with a context sentence, or with the `rationale` of a non-rejected `implies`/`requires-definition` relation from a context THMREF towards this reference. A relation covers only the hypotheses its rationale names; a relation with an empty or unrelated rationale covers none | needs-human-review |
| 7 | `conclusion_supports_claim` (token overlap >= 0.3) | inconclusive |
| 8 | `direction` (converse needs an `equivalent-to` relation) | rejected |
| 9 | `quantifier_agreement` (universal vs existential words in reference vs claim) | rejected |
| 10 | `domain_agreement` (finite/infinite, compact, smooth, real/complex, prime, integer, bounded, connected, convex and `d = 3`-style parameters present in the hypotheses but absent from or contradicted by the context + claim text) | rejected, named mismatch |
| 11 | `not_contradicted` (`contradicts` edge to an *accepted* reference) | rejected |

Result precedence: `rejected > needs-human-review > inconclusive > accepted`.
Because of check 1, only a reference a human has accepted (`theorem review
--status accepted`) can ever come out `accepted`; a model-extracted candidate is
at best `needs-human-review` no matter how well the other checks go.
`performed_by` is `deterministic`; `proposed_analysis` (an LLM's prose, task
class `verification_support`) is stored verbatim and never influences the
result. `assumption_context` entries may be sentences or THMREF ids. The
function reads the dossier only through the CLI (`--claim`) and never writes to
it; `tests/test_theorem_applicability.py` asserts claim statuses are unchanged.

## Coverage categories and levels

Categories: `original_problem_source, definitions_notation,
strongest_known_positive_results, known_negative_results, known_counterexamples,
special_cases, equivalent_formulations, standard_tools_lemmas,
recent_developments, survey_synthesis_sources, unresolved_gaps`.

Levels: `unknown` (no literature signal for the problem at all), `missing`,
`partial`, `adequate`, `conflicting`.

`coverage.assess_coverage(ot_dir, problem_id, mode=None, campaign_id=None,
persist=True)` derives one entry per category:

1. a human override (`theorem coverage --set`) wins;
2. accepted references tagged with the category -> `adequate`, or `conflicting`
   when two of them are linked by `contradicts`;
3. candidate references only -> `partial` (extraction files each candidate under
   a hinted category, so this row is reachable before any review);
4. dossier facts (related papers with a `paper_artifact` -> original problem
   source, known results -> strongest positive results, legacy `THM-*` ->
   standard tools) -> at most `partial`;
5. otherwise `missing` (or `unknown` when nothing at all is recorded).

The number of registered papers is never consulted (a workspace with ten papers
and no categorised references is still insufficient everywhere).
`critical_categories(mode)`: prove-or-refute (also the default) = original
source, definitions, strongest positive, negative results, counterexamples,
equivalent formulations, standard tools; exploration = original source,
definitions, special cases, standard tools; survey = all eleven.
`insufficient = critical` intersected with `{unknown, missing}` -- the campaign
scheduler boosts literature branches while it is non-empty, and a librarian
worker may only ever raise a level to `partial`; `adequate` needs an accepted
reference or a human override.

## CLI

```
opentorus theorem extract PAPER-0001 [--problem PROBLEM-0001] [--llm]
opentorus theorem list [--problem P] [--paper PAPER-0001] [--status candidate|accepted|rejected] [--json]
opentorus theorem show THMREF-0001 [--json]
opentorus theorem link THMREF-0002 THMREF-0001 --relation implies [--rationale "..."]
opentorus theorem check THMREF-0001 --problem PROBLEM-0001 --claim CLAIM-0003 [--json]
opentorus theorem check THMREF-0001 --problem PROBLEM-0001 --claim-text "..." --assume "G is a finite group" [--direction converse]
opentorus theorem review THMREF-0001 --status accepted --note "read the statement on p.3" \
    --category strongest_known_positive_results --root-relation supporting --problem PROBLEM-0001
opentorus theorem coverage PROBLEM-0001 [--mode exploration] [--record] [--json]
opentorus theorem coverage PROBLEM-0001 --set definitions_notation adequate --evidence PAPER-0001 --note "section 2"
```

With `--claim`, the claim statement is the claim text and the dossier's
assumptions (plus any `--assume`) form the context. `theorem review` is also
where a human classifies a reference: `--category` (repeatable) sets the
coverage categories it covers, `--root-relation` its relation to the problem
and `--problem` its attribution; omitted options leave those fields untouched.
`theorem coverage` without options is a read: the map is derived on the fly and
nothing is appended to the coverage ledger (`id` is empty in `--json`); a
`COV-NNNN` assessment is recorded only with `--record` or as part of `--set`.
Exit codes: 0 ok, 1 error
(unknown paper/reference/claim, unparsed paper, bad status/relation/category),
2 when `check` results in `rejected` so scripts can gate on it.
