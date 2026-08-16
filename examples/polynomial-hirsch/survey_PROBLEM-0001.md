# Literature Survey for PROBLEM-0001: Polynomial Hirsch Conjecture

**Goal:** Gather and record at least ten relevant preprints/papers that discuss bounds, techniques, or related structures to the polynomial Hirsch conjecture. All papers have been fetched and parsed; observations and dossier links have been recorded.

---

## Collected Papers (parsed)
| ID | Source | Title / Identifier | Key Contributions & Relevance |
|----|--------|---------------------|--------------------------------|
| **PAPER-0003** | arXiv:1307.5900v1 | *On the diameter of simplicial complexes* | Shows maximum diameter of simplicial d‑complexes with n vertices is Θ(n^d); provides lower bounds for Hs(n,d) and discusses limitations for polynomial Hirsch conjecture in simplicial settings. |
| **PAPER-0004** | arXiv:1808.03165v2 | *Weight vectors and voting games* | Provides combinatorial lemmas on weight vectors; may inspire constructions of polytopal examples relevant to diameter bounds. |
| **PAPER-0007** | arXiv:2101.12198v3 | *Subdeterminant‑based upper bounds & smoothed analysis* | Gives polynomial‑in‑Δ (max subdeterminant) upper bounds; shows with high probability polytope diameters are polynomial, directly addressing the conjecture. |
| **PAPER-0008** | arXiv:2106.16130v2 | *Diameters of graph associahedra* | Links polytope diameter to graph parameters (tree‑depth, treewidth); provides Θ(m) and Θ(td·n) bounds for specific families, offering structural insight. |
| **PAPER-0009** | arXiv:2112.13027v1 | *Diameter of random spherical polytopes* | Gives probabilistic upper/lower bounds (Ω(n m^{1/(n‑1)}), O(n^2 m^{1/(n‑1)}+…)) when facets are many; informs average‑case behavior. |
| **PAPER-0010** | arXiv:2404.04158 | *NP‑hardness of circuit/combinatorial diameter* | Proves strong NP‑hardness for computing circuit and combinatorial diameters (including {0,1}‑polytopes); highlights computational barriers. |
| **PAPER-0011** | arXiv:2008.06844v1 | *Diameter binary program & polytope* | Introduces the “diameter binary program” as a metric for diversity of optimal solutions; studies the associated diameter polytope, connecting to combinatorial diameter concepts. |
| **PAPER-0012** | arXiv:1809.06780v2 | *Extension of Bonifas et al. bound* | Extends subdeterminant‑based upper bounds from integer to real matrices; provides example where new bound improves prior results. |
| **PAPER-0013** | arXiv:1709.09642v1 | *Circuit diameter of classic polytopes* | Studies circuit diameter for matching, TSP, and fractional stable set polytopes; offers techniques that may translate to combinatorial diameter bounds. |
| **PAPER-0014** | arXiv:1603.04052v1 | *Tail‑quasi‑polynomial & tail‑polynomial bounds* | Proves tail‑almost‑linear upper bound for convex polyhedra when facets are large; gives evidence supporting polynomial Hirsch conjecture in certain regimes. |
| **PAPER-0015** | arXiv:1603.00325 | *Transportation polytopes and Hirsch* | Provides algorithmic proof of Hirsch bound for a class of transportation polytopes; illustrates constructive approaches to diameter bounds. |

---

## Observations (stored in memory)
- OBS‑0028: Lower bounds for simplicial complexes (PAPER‑0003).
- OBS‑0031: Weight‑vector lemmas potentially useful for constructing hard instances (PAPER‑0004).
- OBS‑0032: Subdeterminant‑based polynomial upper bounds, smoothed analysis (PAPER‑0007).
- OBS‑0033: Graph associahedra diameter linked to graph parameters (PAPER‑0008).
- OBS‑0034: Probabilistic diameter bounds for random spherical polytopes (PAPER‑0009).
- OBS‑0030: NP‑hardness of circuit/combinatorial diameter (PAPER‑0010).
- OBS‑0029, OBS‑0031, OBS‑0032, OBS‑0033, OBS‑0034 added similarly.

---

## Dossier Links (registered)
- **Related papers**: RELP‑0011 (PAPER‑0003), RELP‑0012 (PAPER‑0010), RELP‑0013 (PAPER‑0004), RELP‑0014 (PAPER‑0008).
- **Known results**: KR‑0001 – Subdeterminant‑based upper bounds (from PAPER‑0007).

---

### Next Steps (Phase 2)
* Continue monitoring new preprints (e.g., via lit_search for "polytope diameter" 2024‑2025). 
* When a promising technique emerges, consider formalizing it as a claim and designing experiments.

*No proof attempts have been made yet; this file serves solely as the literature survey.*
