# Literature Survey for PROBLEM‑0001 (Tensor Concentration)

**Goal:** Gather at least five preprints that are directly relevant to Conjecture 16 (type‑2 constant of tensors). All papers below have been fetched, parsed, and their key results recorded as observations.

---

## Papers collected

| Paper ID | arXiv / DOI | Key result(s) cited | Relevance to Conjecture 16 |
|----------|--------------|---------------------|----------------------------|
| **PAPER‑0001** | arXiv:2411.10633 | Theorem 1.6 gives an upper bound on the type‑2 constant \(C_{r,p}(d)\) for the ℓₚ injective norm of order‑r tensors, matching the conjectured scaling \(d^{½-1/p}\) up to logarithmic factors. | Directly addresses Conjecture 16 by providing a (near‑optimal) upper bound on the quantity of interest. |
| **PAPER‑0002** | arXiv:2412.21193 | Theorem 1.1 shows that for a Gaussian tensor with independent entries, \(c\sqrt d \le \mathbb{E}\|Z\|_{inj} \le C(r)\sqrt d\). This establishes the baseline √d scaling of the injective norm. | Supplies a basic lower/upper bound that underpins the dimension dependence appearing in Conjecture 16 (the case \(p=2\)). |
| **PAPER‑0003** | arXiv:2404.03627 | Theorem 1.1 (main theorem) provides a one‑sided bound on the expected injective norm of a Gaussian tensor that scales as \(d^{½-1/p}\,\sqrt{\sum_i\|T_i\|_{I_p}^2}\), matching the conjectured dependence up to constants. | Gives precisely the form appearing in Conjecture 16 (without log factors) for a broad range of \(p\). |
| **PAPER‑0004** | arXiv:2509.03439 | Lemma 4.1 (pp. 6) gives a sub‑Weibull concentration inequality for the Euclidean norm of vectors with independent \(S_α\)-sub‑exponential coordinates. | Provides tail bounds that can be used to handle heavy‑tailed tensor entries when extending Gaussian concentration arguments. |
| **PAPER‑0005** | arXiv:2603.01342 | Theorem 2.1 (pp. 5) gives an upper bound on the injective norm of any deterministic tensor in terms of averaged projections onto random unit vectors. | Offers a deterministic tool that may be combined with Gaussian averaging to control the type‑2 constant. |

---

## Observations recorded in the knowledge base

- **OBS‑0014** – PAPER‑0001 Theorem 1.6 provides an upper bound on the type‑2 constant \(C_{r,p}(d)\) with \(d^{½‑1/p}\) scaling (up to log factors).
- **OBS‑0015** – PAPER‑0002 Theorem 1.1 establishes √d scaling for the expected injective norm of a Gaussian tensor with independent entries.
- **OBS‑0017** – PAPER‑0003 Theorem 1.1 gives a one‑sided bound matching the conjectured dimension dependence.
- **OBS‑0018** – PAPER‑0004 Lemma 4.1 supplies sub‑Weibull concentration for vectors with independent heavy‑tailed coordinates.
- **OBS‑0019** – PAPER‑0005 Theorem 2.1 provides a deterministic bound on the injective norm via random projections.

---

## Dossier links (automatically created)

- **RELP‑0006** → PROBLEM‑0001: PAPER‑0001 – Upper bound on \(C_{r,p}(d)\).
- **RELP‑0007** → PROBLEM‑0001: PAPER‑0003 – One‑sided bound matching conjectured scaling.
- **RELP‑0008** → PROBLEM‑0001: PAPER‑0002 – Baseline √d behavior.
- **RELP‑0009** → PROBLEM‑0001: PAPER‑0005 – Deterministic projection bound.
- **RELP‑0010** (implicitly created) → PROBLEM‑0001: PAPER‑0004 – Heavy‑tail concentration tool.

---

### Next steps (phase 2)
* Use the observations and tools above to design concrete proof strategies or experiments.
* If additional literature is needed, perform further lit_search queries focusing on heavy‑tailed tensor concentration or generic chaining techniques.

*All artifacts are now recorded; no proof attempts have been made yet.*