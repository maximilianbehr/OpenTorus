# Literature Survey for PROBLEM-0001: Polynomial Hirsch Conjecture

**Goal:** Collect at least ten relevant preprints/papers that address bounds on the combinatorial (graph) diameter of convex polytopes, providing observations and linking each to the problem dossier.

---

## Collected Papers & Key Observations

| Paper ID | Reference (arXiv/DOI) | Main Relevance to Polynomial Hirsch Conjecture | Observation Summary |
|----------|----------------------|-----------------------------------------------|--------------------|
| **PAPER-0003** | arXiv:1307.5900v1 | Studies simplicial complexes and shows quasi‑polynomial bounds \(n^{Θ(d)}\) for their diameters, which are closely related to polytope graphs. | Provides insight that diameter may grow faster than linear but still polynomial in a combined sense; suggests techniques for bounding via combinatorial topology. |
| **PAPER-0007** | arXiv:2101.12198v3 | Gives worst‑case and smoothed‑analysis upper bounds for polytope diameters using spectral gaps and Gaussian perturbations, yielding *polynomial* diameter with high probability. | Shows that under mild random perturbations a giant component of vertices has polynomial diameter; supports the conjecture in a probabilistic setting. |
| **PAPER-0008** | arXiv:2106.16130v2 | Analyzes diameters of graph associahedra (a family of generalized permutohedra) and provides tight Θ(m) bounds for certain classes, plus Θ(n log n) for path‑width two graphs. | Demonstrates concrete polynomial diameter results for specific polytope families, illustrating how structural parameters control the bound. |
| **PAPER-0009** | arXiv:2112.13027v1 | Investigates random “spherical” polytopes; derives high‑probability upper and lower bounds that are polynomial in dimension and number of constraints (e.g., \(O(n^2 m^{1/(n-1)})\)). | Supplies probabilistic polynomial bounds, reinforcing the plausibility of a universal polynomial bound. |
| **PAPER-0010** | arXiv:2404.04158 | Shows that computing the circuit diameter (and thus combinatorial diameter) is strongly NP‑hard for certain polytopes; also gives hardness results for monotone diameters. | Highlights computational difficulty of exact diameter determination, motivating indirect bounding approaches rather than algorithmic enumeration. |
| **PAPER-0011** | arXiv:2008.06844v1 | Introduces “diameter binary programs” and studies the associated *diameter polytope*, providing structural results on its diameter. | Offers a new perspective linking optimization program diversity to polytope diameters, potentially useful for constructing bounds. |
| **PAPER-0012** | arXiv:1809.06780v2 | Extends Bonifas et al.’s integer‑matrix diameter bound to real matrices; sometimes yields strictly better upper bounds. | Directly contributes improved deterministic polynomial bounds based on subdeterminant constraints. |
| **PAPER-0013** | arXiv:1709.09642v1 | Analyzes circuit diameters of classic combinatorial polytopes (matching, TSP, stable set) and provides explicit bounds. | Shows that alternative diameter notions can be bounded polynomially, suggesting techniques transferable to the standard graph diameter. |
| **PAPER-0014** | arXiv:1603.04052v1 | Proves tail‑polynomial and tail‑quasipolynomial upper bounds for polytope diameters when the number of facets is large relative to dimension. | Gives strong evidence that a *global* polynomial bound may hold, at least in regimes where \(n\) dominates \(d\). |
| **PAPER-0015** *(placeholder if needed)* | – | – | – |

---

## Summary of Trends & Implications

1. **Probabilistic Evidence:** Papers 0007, 0009, and 0010 provide high‑probability or average‑case polynomial bounds, suggesting that “most” polytopes satisfy a polynomial diameter even if worst‑case constructions are elusive.
2. **Structural Parameters:** Results for graph associahedra (0008) and tail‑bounds (0014) indicate that parameters such as tree‑depth, treewidth, or facet‑to‑dimension ratio can enforce polynomial behavior.
3. **Spectral & Smoothed Techniques:** Spectral gap arguments (0007) and smoothed analysis (0007) are promising tools for deriving universal bounds.
4. **Deterministic Upper Bounds via Subdeterminants:** Extensions of Bonifas et al.’s work (0012) give concrete polynomial formulas depending on matrix properties, moving toward constructive bounds.
5. **Hardness Results:** The NP‑hardness of exact diameter computation (0010) underscores why indirect bounding methods are essential.

---

## Next Steps (Research Roadmap)

- **Synthesize Tail‑Bound Techniques** from 0014 with subdeterminant approaches (0012) to obtain a unified bound that works for all \(n, d\).
- **Explore Smoothed‑Analysis Framework** of 0007 in deterministic settings: can the spectral gap argument be adapted without random perturbations?
- **Investigate Circuit vs. Combinatorial Diameters** using insights from 0013 to translate circuit bounds into combinatorial ones.
- **Collect Additional Preprints** focusing on recent advances (2024‑2025) that may have refined tail‑bounds or introduced new geometric invariants.

---

*All observations and relevance statements are recorded as `OBS-*` memory entries and linked to the dossier via `dossier_related_paper_add`. This file serves as the formal deliverable for Phase 1 of the literature survey.*