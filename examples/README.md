# OpenTorus examples

Real, runnable end-to-end workflows on actual open problems. Each example is a
driver script that sets up a fresh `.opentorus/` workspace, configures a model,
registers the source paper(s), creates the problem dossier(s), runs the agent,
and builds an honesty-linted report.

> OpenTorus is a research-engineering shell around a capable LLM: tools, papers,
> experiments, claims, and an audit trail under `.opentorus/`. The model does the
> reasoning; OpenTorus makes the work inspectable, reproducible, and honest.

> **Each driver resets the local workspace** (`rm -rf .opentorus`) and defaults to
> a local Ollama model on `http://localhost:11434`. Run it in a scratch directory;
> override the model, endpoint or provider with `OPENTORUS_MODEL` /
> `OPENTORUS_BASE_URL` / `OPENTORUS_PROVIDER` (e.g. `openai` for a vLLM server:
> `OPENTORUS_PROVIDER=openai OPENTORUS_BASE_URL=http://localhost:8000/v1
> OPENTORUS_MODEL=<served-model-name> OPENAI_API_KEY=x`), or edit the
> `opentorus config set model.*` lines for your own provider. The campaign
> drivers also take `OPENTORUS_MODE` (prove-or-refute / exploration / survey),
> `OPENTORUS_BRANCHES`, `OPENTORUS_MAX_STEPS`, `OPENTORUS_BRANCH_STEPS`,
> `OPENTORUS_MAX_WALL_SECONDS` and `OPENTORUS_SMT=true` (lets the formalizer use
> a `z3` on your PATH; default off).

---

## The examples

| Directory | Problem | Numerics | Run |
|-----------|---------|----------|-----|
| [simons-eigenvalue-problems](simons-eigenvalue-problems/) | Thirteen small eigenvalue / linear-systems open problems from a Simons workshop (arXiv:2602.05394; 41 numbered problems in the paper): Ritz-value conditioning, CG vs randomized coordinate descent, eigenvalue clustering vs GMRES, invariant-subspace Ritz approximation, deterministic diagonal gaps, the Forsythe conjecture, finite-precision CG residuals and bit requirements, Ritz values over the numerical range, MR3 bidiagonal SVD failure modes, GECP on the fermionic kernel, QRCP row selection on orthonormal columns, volume sampling vs optimal subset selection. | yes (containerized `scripts/`) | `./simons_open_problems.sh [PROBLEM-ID]` |
| [matrix-functions](matrix-functions/) | Five open problems on limited-memory polynomial methods for `f(A)b` (Güttel, Kressner, Lund; arXiv:2002.01682): optimal restart length, a posteriori error estimation, stable first column of `f(H_m)`, two-pass Lanczos orthogonality loss, spectrum-adaptive polynomial methods. | yes (agent-written, containerized) | `./matrix_functions_open_problems.sh [PROBLEM-ID]` |
| [polynomial-hirsch](polynomial-hirsch/) | Polynomial Hirsch Conjecture: does a polynomial `p(n,d)` bound the graph diameter of every `d`-dimensional polytope with `n` facets? Literature dossier + **polymake** experiments: certified diameters, Santos-record reproduction, and spindle search (a `d`-spindle of length `> d` is a finite Hirsch-violating certificate). | yes (agent-written, containerized **polymake**) | `bash poly_hirsch_sota.sh` |
| [backward-error-convergence](backward-error-convergence/) | Is randomness necessary for condition-number-independent backward-error convergence in general linear-system solvers? (arXiv:2604.16075) | no | `bash minberr_backward_error.sh` |
| [nystrom-submodularity](nystrom-submodularity/) | Is the nuclear-norm Nyström approximation error submodular for SDD/SDDM positive-definite matrices? Ships a finished [sample dossier](nystrom-submodularity/sample-output/). | yes (agent-written, containerized) | `bash nystroem_submodularity.sh` |
| [matrix-sign-approximation](matrix-sign-approximation/) | Asymptotic minimax error of the best degree-`2^m`-computable polynomial approximating the matrix sign function on `[-1,-δ] ∪ [δ,1]` (arXiv:2504.01500). | no | `bash sign.sh` |
| [random-nla](random-nla/) | Adaptive sketch size for randomized low-rank approximation: an a posteriori error estimate driving an adaptive `ℓ = k + p` in the randomized SVD / range finder, and the oversampling each spectral-decay profile needs (Martinsson & Tropp survey, arXiv:2002.01387). | yes (agent-written, containerized) | `bash adaptive_sketch_size.sh` |
| [tensor-concentration](tensor-concentration/) | The type-2 constant of tensors (Conjecture 16): does `E‖Σ gᵢTᵢ‖_{ℐₚ} ≤ Õ_{r,p}(d^{1/2−1/p}·√Σ‖Tᵢ‖_{ℐₚ}²)` for the symmetric injective `ℓₚ` norm? Settled for `p ≥ 2r` (arXiv:2411.10633); open for `p < 2r` and rank `r ≥ 3` (Lucca, randomstrasse101 blog). | yes (agent-written, containerized) | `bash tensor_concentration.sh` |
| [gecp-growth-factor](gecp-growth-factor/) | Wilkinson's 1961 question: is the maximum growth factor `g(n)` of Gaussian elimination with complete pivoting polynomial in `n`? Quasi-polynomial upper bound vs. linear lower bounds (arXiv:2303.04892, arXiv:2312.00994); even `g(5)` is unknown. | yes (agent-written, containerized) | `bash gecp_growth_factor.sh` |
| [matrix-spencer](matrix-spencer/) | Matrix Spencer conjecture: signs `εᵢ` with `‖Σ εᵢAᵢ‖ ≤ C√n` for symmetric norm-1 matrices? Known up to polylog rank (arXiv:2208.11286); open in general. | yes (agent-written, containerized) | `bash matrix_spencer.sh` |
| [marcus-de-oliveira](marcus-de-oliveira/) | Marcus–de Oliveira determinantal conjecture: `det(A+UBU*)` inside the hull of `Π(aᵢ+b_σ(i))` for normal `A,B`? Open 50+ years, even `n=4` with `A` Hermitian. A designated counterexample-verification workflow. | yes (agent-written, containerized) | `bash marcus_de_oliveira.sh` |
| [komlos-conjecture](komlos-conjecture/) | Komlós conjecture: a universal constant `K` bounding `min_ε ‖Σ εᵢvᵢ‖_∞` for unit vectors? Best upper bound `Õ(log^{1/4} n)` (Bansal–Jiang, arXiv:2508.03961, after Banaszczyk's `O(√log n)`); lower bound `K ≥ 1+√2` (Kunisky); implies Beck–Fiala. | yes (agent-written, containerized; z3 in container) | `bash komlos.sh` |
| [kalai-3d](kalai-3d/) | Kalai's `3^d` conjecture: every centrally symmetric `d`-polytope has `≥ 3^d` nonempty faces. True for `d ≤ 4`; open for `d ≥ 5` (`3^5 = 243`). | yes (agent-written, containerized) | `bash kalai_3d.sh` |
| [bollobas-nikiforov](bollobas-nikiforov/) | Bollobás–Nikiforov conjecture: `λ₁² + λ₂² ≤ 2m(1 − 1/ω)` for `G ≠ Kₙ`. Known triangle-free/regular/multipartite/dense-K₄-free; open in general. Candidate violations are finite certificates. | yes (agent-written, containerized; networkx) | `bash bollobas_nikiforov.sh` |
| [lehmer-problem](lehmer-problem/) | Lehmer's Mahler measure problem (1933): is `inf{M(p) : M(p) > 1} > 1`? Record `M ≈ 1.17628` unbeaten for 90+ years; nonreciprocal case settled (Smyth). | yes (agent-written, containerized) | `bash lehmer.sh` |
| [difference-triangle-set](difference-triangle-set/) | A `(7,5)`-difference triangle set with scope ≤ 111: seven rows, 105 pairwise-distinct differences; scope 112 known. The most certificate-friendly target — constructions need two independent validators + exact `proof_submit` re-check, nonexistence needs a DRAT/LRAT/SMT certificate, and the statement ships a five-phase workflow with a strict claim policy. | yes (agent-written, containerized; CP-SAT + z3 + python-sat) | `bash dts.sh` |
| [rbm-universality-divergence](rbm-universality-divergence/) | Two small restricted Boltzmann machines from the [AIM Boltzmann-machines list](http://aimpl.org/boltzmann/1/) (1.1/1.2, Montúfar): does the closure of `RBM_{4,3}` fill the 15-simplex, and what is the maximum KL divergence of `RBM_{3,1}` (known ≤ 1 bit; conjectured `−(3/4)log₂(2√3−3) ≈ 0.8306`)? Audited 2026-08-17 (counter-checked): both open; creation-time fits found soft-parity targets that `RBM_{4,3}` fits cannot reach (≈ 0.077 bits residual with diverging parameters, reproduced by an independent implementation) — evidence *against* the fullness the page's simulations suggested — and reproduced the conjectured `RBM_{3,1}` value to seven digits. Fixed-instance dossier, not a campaign. | yes (agent-written, containerized; numpy/scipy/sympy) | `bash rbm_universality_divergence.sh` |

### Campaign examples (general-conjecture scope policy)

Built from [CAMPAIGN_TEMPLATE.md](CAMPAIGN_TEMPLATE.md): the primary target is the full
quantified conjecture (fixed instances are internal tools), the driver designates the
primary claim deterministically, the task text runs a dual research process (refutation +
proof track), and `opentorus problem verdict` derives the terminal classification. Status
audits are fresh, dated web checks at creation time.

> **The engine now does what these drivers script by hand.** `opentorus campaign start
> PROBLEM-XXXX --mode prove-or-refute` replaces the bash drivers' orchestration: it
> designates the CONJECTURE primary claim, opens a portfolio of distinct branches (proof
> route, counterexample search, literature map, formalization, special cases, ...),
> schedules bounded work items across them, remembers failed attempts, and records every
> decision in a replayable event log under the dossier. The drivers below remain valid
> for what they set up around it (workspace, model, papers, dossier statement) and as
> worked examples of the scope policy; the terminal classification is still
> `opentorus problem verdict` -- a completed campaign does not mean the problem is
> solved. See [docs/campaign-engine.md](../docs/campaign-engine.md).

| Directory | Conjecture | Audit (2026-08-14) | Run |
|-----------|-----------|--------------------|-----|
| [graceful-tree](graceful-tree/) | Every tree admits a graceful labeling (Ringel–Kotzig 1964). | Open; verified ≤ 35 vertices; "almost all trees almost graceful" (arXiv:1608.01577); a 2007 claimed proof is unaccepted. | `bash graceful_tree.sh` |
| [barnette](barnette/) | Every 3-connected cubic planar bipartite graph is Hamiltonian (Barnette 1969). | Open; verified n ≤ 90; the neighboring Barnette–Goodey conjecture was proved (Kardoš 2020) — recorded as a settled neighbor. | `bash barnette.sh` |
| [caccetta-haggkvist](caccetta-haggkvist/) | Min out-degree ≥ n/k forces a directed cycle of length ≤ k, for every k (1978). | Widely open, even k = 3; small independence number proved (arXiv:1908.02902); triangle frontier [n/3, 0.3465n]. | `bash caccetta_haggkvist.sh` |
| [frankl-union-closed](frankl-union-closed/) | Some element belongs to ≥ half the members of every union-closed family (Frankl 1979). | Open; Gilmer-line constant (3−√5)/2 ≈ 0.382 (arXiv:2211.11689 + refinements), proven optimal for the *approximate* version — new ideas needed for 1/2. | `bash frankl.sh` |
| [lonely-runner](lonely-runner/) | Every runner among k+1 with distinct speeds gets circular distance ≥ 1/(k+1) from all others, for every k (Wills 1967 / Cusick 1974). | Open in general; ≤ 13 runners settled (k ≤ 12), 8–13 all 2025/26 computer-assisted (Rosenfeld arXiv:2509.14111; arXiv:2511.22427; arXiv:2512.01912; arXiv:2604.23906) — the frontier method is itself computational. | `bash lonely_runner.sh` |
| [sidorenko](sidorenko/) | t_H(G) ≥ t_{K₂}(G)^{e(H)} for every bipartite H and every G (Sidorenko 1993). | Open; broad settled classes (suitable blow-ups arXiv:1809.01259, subdivisions arXiv:2408.03491), approximate version holds; simplest unknown case K₅,₅∖C₁₀ (the 10-vertex Möbius ladder). | `bash sidorenko.sh` |

| Directory | Conjecture | Audit (2026-08-17) | Run |
|-----------|-----------|--------------------|-----|
| [hadamard](hadamard/) | A Hadamard matrix of order 4k exists for every k (Hadamard 1893). | Open in general; days before the audit (2026-08-12/13) an Anthropic team **announced** matrices for all 12 unknown orders < 2000 — third-party integer-verified, no arXiv paper, unrefereed; density of settled orders in 4ℕ still 0. | `bash hadamard.sh` |
| [erdos-straus](erdos-straus/) | 4/n = 1/x + 1/y + 1/z solvable in positive integers for every n ≥ 2 (Erdős–Straus 1948). | Open; verified n ≤ 10^17 (Salez, arXiv:1406.6307; a 10^18 claim is unrefereed); identities cover all classes mod 840 except the six square classes, and no finite identity system can close them (Schinzel obstruction, arXiv:1107.1010); a Feb 2026 claimed proof is publicly doubted. | `bash erdos_straus.sh` |
| [distinct-subset-sums](distinct-subset-sums/) | Sets with distinct subset sums have max ≥ c·2^n for a universal c > 0 (Erdős problem #1, $500). | Open; best bounds √(2/π)·2^n/√n (arXiv:2006.12988) vs 0.22002·2^n (Bohman 1998); exact minima known only for n ≤ 10 (a(10) = 309, Dyson 2025, OEIS A276661). | `bash distinct_subset_sums.sh` |
| [happy-ending](happy-ending/) | ES(n) = 2^{n−2}+1: every 2^{n−2}+1 points in general position contain a convex n-gon (Erdős–Szekeres 1935). | Open; ES(6) = 17 (Szekeres–Peters 2006; SAT re-verified in seconds, arXiv:2403.00737); ES(7) = 33 open with only anchored-subfamily certificates (arXiv:2512.24061); best upper bound 2^{n+O(√(n log n))} (arXiv:1710.11415). | `bash happy_ending.sh` |
| [one-third-two-thirds](one-third-two-thirds/) | Every finite non-chain poset has a pair x, y with Pr[x ≺ y] ∈ [1/3, 2/3] (Kislitsyn 1968). | Open; verified through n = 14 by a 1.34-trillion-poset census (arXiv:2607.23926, Jul 2026); best general constant (5−√5)/10 ≈ 0.2764 (BFT 1995); width 3 open (record 14/39). | `bash one_third_two_thirds.sh` |
| [erdos-gyarfas](erdos-gyarfas/) | Every graph with min degree 3 has a cycle of length a power of 2 (Erdős–Gyárfás ~1995). | Open; planar claw-free, 3-connected cubic planar, P₁₃-free settled; large *average* degree suffices (Liu–Montgomery, JAMS 2023, arXiv:2010.15802); cubic bipartite counterexamples need ≥ 60 vertices (arXiv:2608.02675, Aug 2026). | `bash erdos_gyarfas.sh` |
| [second-neighborhood](second-neighborhood/) | Every oriented graph has a vertex with \|N⁺⁺\| ≥ \|N⁺\| (Seymour 1990). | Open; tournaments settled (Havet–Thomassé 2000); general constant 0.7155 (arXiv:2412.20234, Dec 2024); min out-degree ≤ 7 (computer-assisted preprint arXiv:2606.30588); a counterexample needs ≥ 17 vertices; one unverified proof claim (arXiv:2501.00614). | `bash second_neighborhood.sh` |
| [ryser-brualdi-stein](ryser-brualdi-stein/) | Every Latin square has an (n−1)-transversal; odd order has a full transversal (Ryser 1967; Brualdi–Stein). | Mixed frontier: n−1 proved for all large n — parity-free — in a still-unpublished preprint (Montgomery, arXiv:2310.19779); Ryser's odd case open, verified ≤ 9 (McKay–McLeod–Wanless 2006); Hall–Paige settled for groups (2009). | `bash ryser_brualdi_stein.sh` |
| [hot-spots](hot-spots/) | Second Neumann eigenfunctions of planar convex domains attain extrema on the boundary (Rauch 1974). | Planar case open (all triangles settled: Judge–Mondal, Annals 2020/22); the high-dimensional convex case was **refuted** in a still-unpublished Dec 2024 preprint (arXiv:2412.06344); non-convex counterexamples have holes (Burdzy–Werner 1999). | `bash hot_spots.sh` |
| [smale-mean-value](smale-mean-value/) | Some critical point ζ has \|p(z)−p(ζ)\| ≤ \|z−ζ\|·\|p'(z)\| for every polynomial p, every z (Smale 1981). | Open; K ≤ 4 − 2.263/√d (Crane 2007); sharp (d−1)/d known only for d ≤ 5 (d = 5: Crane, CMFT 2006); 6 ≤ d ≤ 10 numerical only; all arXiv proof claims unaccepted; the dual conjecture is proved for d ≤ 7 (arXiv:2303.17586). | `bash smale_mean_value.sh` |

| Directory | Conjecture ([Randomstrasse101](https://randomstrasse101.math.ethz.ch/) — ETH Zürich open-problems blog) | Audit (2026-08-17) | Run |
|-----------|-----------|--------------------|-----|
| [kuramoto-density-threshold](kuramoto-density-threshold/) | For every ε there is a graph with min degree ≥ (3/4−ε)n that is not globally synchronizing (Kuramoto; RS101 #5). | Open; upper half is a theorem (min degree ≥ 0.75(n−1) ⇒ synchrony, arXiv:2105.11406, and 0.75 is the linear-stability limit); lower bound μ_c > 0.6838; neighbors: random cubic graphs open (d ≥ 35 known, arXiv:2503.18801), signed Kuramoto RESOLVED (McRae 2025). Twisted-state Hessians give exact certificates — a certified graph above 0.6838 is real progress. | `bash kuramoto_density_threshold.sh` |
| [sign-matrix-discrepancy](sign-matrix-discrepancy/) | An infinite family of ±1 matrices with disc(A) ≥ (1+δ)√n (RS101 #12; #11 asks the exact Spencer constant). | Open; exact maxima 2,1,2,3,4 for n = 2..6 computed at creation (ratio 1.633 at n = 6, above √2); Sylvester odd-k neighbor (#13) refuted for all odd k ≥ 9 via Boolean nonlinearity, leaving the H_k family available for #12. | `bash sign_matrix_discrepancy.sh` |
| [paley-clique](paley-clique/) | ω(G_p) = O(polylog p) for every prime p ≡ 1 (4) (RS101 #25; localizations #26–28 and the Paley-ETF RIP #29 as tools). | Open; only √(p/2)+1 (Hanson–Petridis, arXiv:1905.09134) beats √p; degree-4 SoS provably ≥ Ω(p^{1/3}) (arXiv:2211.02713); the 1-localization LP with exact rational duals yields certified per-p clique bounds. | `bash paley_clique.sh` |
| [balan-wang-stability](balan-wang-stability/) | ω(A) ≤ C max‖A_k‖ β^M for every full-spark A ∈ ℝ^{(2M−1)×M} — exponentially bad phase-retrieval stability at the minimal measurement count (RS101 #20). | Open for general A; Gaussian case settled at exponential scale (ω = 4^{−m+o(m)}, Shmalo arXiv:2607.06249, Jul 2026 ⇒ any β ≥ 1/4); ω exact for M ≤ 10 (≤ 92,378 submatrices). | `bash balan_wang_stability.sh` |
| [kls-conjecture](kls-conjecture/) | Universal Cheeger/Poincaré constant for every isotropic log-concave measure (KLS 1995; RS101 #30). | Open; best established ψ_n ≥ c(log n)^{−1/2} (Klartag 2023); slicing (Klartag–Lehec Dec 2024) and thin shell (Klartag–Lehec 2025) now THEOREMS with universal constants; (log n)^{−1/4} CLAIMED by two concurrent GPT-5.6-Pro-assisted July-2026 preprints (Chen–Klartag arXiv:2607.23307; Letwin arXiv:2607.24164), unrefereed. Exact polynomial Poincaré bounds on rational polytopes as instance program. | `bash kls_conjecture.sh` |
| [lovasz-theta-random](lovasz-theta-random/) | E ϑ(G) = (1+o(1))√n for random dense circulant graphs (RS101 #18; #17 for G(n,1/2) as sibling). | Open; rigorous √n ≤ E ϑ ≤ C√(n log log n) (arXiv:2502.16227); G(n,1/2): [√n, 2√n] for 40 years, heuristic 1.55 conjecture (Feige–Grinberg arXiv:2506.02952). ϑ of a circulant graph is an LP — exact rational certificates, n ~ 10⁴ routine. | `bash lovasz_theta_random.sh` |

| Directory | Conjecture ([AIM Problem Lists](https://aimath.org/problemlists/) — aimpl.org, http only) | Audit (2026-08-17) | Run |
|-----------|-----------|--------------------|-----|
| [ramanujan-signings](ramanujan-signings/) | A random signing of every d-regular Ramanujan graph has ‖S‖ < 2√(d−1)+ε with constant probability (block model list §5, Srivastava). | Partially resolved: yes whp for bicycle-free radius ≫ (log log n)² — LPS, random regular (Mohanty–O'Donnell–Paredes, arXiv:1909.06988); open for Ramanujan bases with many short cycles; a June 2026 deterministic-signing preprint withdrawn. Exact enumeration over signings of small Ramanujan graphs at creation (Petersen .97, K₄ .75, …). | `bash ramanujan_signings.sh` |
| [nonbacktracking-ramanujan](nonbacktracking-ramanujan/) | Alon–Boppana for the non-backtracking Ramanujan notion: \|λ₂(B)\| ≥ √ρ − o(1) for connected graphs with NB Perron eigenvalue exactly ρ (block model §5.4, Massoulié; = spectralhypergraph 1.3(2)). | Open for the connected exact-ρ version — and **false for two literal readings**: an 8-vertex minimiser with a long cycle attached keeps ratio 0.94705 while n → ∞ and ρₙ → ρ (certified at creation, independently re-run); upper side proved for sparse ER (arXiv:1501.06087) and lifts (arXiv:1502.04482). | `bash nonbacktracking_ramanujan.sh` |
| [sos-coloring-ks](sos-coloring-ks/) | No constant-degree SoS refutation of k-colorability below the Kesten–Stigum bound d = (k−1)² (block model §3.2, Moore). | Open above degree 2; Lovász θ fails far above KS (refutes only for d ≳ 4(k−1)², arXiv:1705.01194, arXiv:1907.02539); quiet-planting evidence to ≈4(k−1)² (arXiv:2008.12237); rigorous SoS lower bounds only for d ≥ log n (Potechin–Xu STOC 2025, no arXiv). Hoffman thresholds reproduced at creation. | `bash sos_coloring_ks.sh` |
| [potts-censoring](potts-censoring/) | Censoring updates can only increase TV distance for ferromagnetic q-state Potts Glauber dynamics from a constant start (markovmixing 1.5, Peres). | Open; Peres–Winkler covers monotone systems only (arXiv:1112.0603); Holroyd refuted the antiferro/colouring analogues (arXiv:1101.4690) and states the ferro constant-start case open; exhaustive exact search on tiny graphs at creation (independently re-run): zero violations, controls reproduce Holroyd. | `bash potts_censoring.sh` |
| [order-polynomial-monotonicity](order-polynomial-monotonicity/) | Kahn–Saks: Ω(P,t)/tⁿ is nonincreasing in t for every finite poset P (ehrhartineq 2.12; Stanley EC1 Ex. 3.163(b), rated [5]). | Open; monotone along t, 2t, 4t… and stronger implying conjectures (Chan–Pak–Panova, arXiv:2205.02798); trivial for nonneg-coefficient classes (skew shapes, fences, arXiv:2503.16403); verified at creation for all posets n ≤ 9 (t ≤ 12), complete all-t certificates n ≤ 8, plus a stronger coefficient-positivity pattern. | `bash order_polynomial_monotonicity.sh` |
| [fisk-toeplitz-minors](fisk-toeplitz-minors/) | The 3×3 Toeplitz-minor transform of a real-rooted polynomial with positive coefficients is real-rooted (totalpos 1.6 = hyperbolicpoly 3.2, Fisk). | Open for 3×3 and all m ≥ 3; Brändén proved 2×2 (arXiv:0909.1927); Yoshida (arXiv:1005.4218) proved the binomial family and refuted the adjacent r = 6 question; ~1350 random real-rooted polynomials pass at creation (exact Sturm), and a discriminant argument proves degree ≤ 4. | `bash fisk_toeplitz_minors.sh` |
| [stable-kneser-chromatic](stable-kneser-chromatic/) | Meunier: χ(KG_s(n,k)) = n − sk + s for every s, k and n > sk (albertson 8.1, Zerbib). | Open in general; s = 2 (Schrijver), even s (Chen 2015), k = 2 (arXiv:2003.08255), s = 3 with k = 3 or n ≥ k³+3k² (Chen–Parker–Zerbib, arXiv:2607.12912, Jul 2026); twelve open s = 3 instances SAT-certified at creation (e.g. χ(KG₃(19,5)) = 7). | `bash stable_kneser_chromatic.sh` |
| [durfee-real-roots](durfee-real-roots/) | Canfield–Corteel–Savage: the Durfee polynomial D_n(x) = Σ_{λ⊢n} x^{D(λ)} has only real roots for every n (polypartition 1.2). | Open; CCS 1998 verified n ≤ 1000 and proved only asymptotic central log-concavity and mean/mode; Rogers–Ramanujan relative fails at n = 75; the 2016 AIM group's recursion/Brenti routes gave nothing; re-certified at creation (exact Sturm counts) for n ≤ 800, twice independently. | `bash durfee_real_roots.sh` |
| [bukh-nonlinear-roth](bukh-nonlinear-roth/) | Bukh: for every nonlinear P and A ⊂ F_p with \|A\| > p^{0.99} there are distinct x, y ∈ A with y + P(x) − P(y) ∈ A (highdimdiscrete 2.1; P = 2x is Roth). | Open; nothing beyond the linear case; not a Peluse-type progression (base-point-dependent shift, not translation-invariant), so the Bourgain–Chang / Peluse / Dong–Li–Sawin bounds do not apply; exact maximum pattern-free sets for p ≤ 59 computed at creation, twice (P = x²: 11 at p = 59 vs p^{0.99} = 56.6). | `bash bukh_nonlinear_roth.sh` |
| [distance-antimagic](distance-antimagic/) | Kamatchi–Arumugam: a graph is distance antimagic iff all open neighbourhoods are distinct (graphstructureapp 1.45; arXiv:1312.7405 Conj. 3.1). | Open; class-by-class results only (paths, cycles, wheels, hypercubes, products, joins, circulants…); exhaustive to order 8 in the literature, extended to order 9 at creation (205 914 graphs, all labelled; order 8 reproduced independently); counter-audit fixed a too-strong printed condition (K₃□K₂ is distance antimagic). | `bash distance_antimagic.sh` |
| [hypercube-random-neighbourhoods](hypercube-random-neighbourhoods/) | Lovett: discrepancy of the set system on {0,1}ⁿ where each vertex owns a random subset of its neighbours (hereddiscrep 1.25) — conjectured Θ(√n) with no polylog. | Open; no paper treats it; Õ(√n) via Bansal–Jiang 2025 (arXiv:2508.03961; exactly the logarithmic-sparsity boundary Altschuler–Tikhomirov 2026 leave open), Ω(√n) w.h.p. via a first-moment + Littlewood–Offord argument derived and independently re-checked at creation; exact SAT values 1–2 for n ≤ 9. | `bash hypercube_random_neighbourhoods.sh` |
| [increasing-paths-sum](increasing-paths-sum/) | Chung–Graham: Σ_v t(v) ≥ \|E\| for every graph and every edge ordering, t(v) the longest increasing path from v (graphramsey 1.38, Graham; implies altitude f(K_n) ≥ (n−1)/2). | Open (both the sum and f(K_n) ≥ cn); n^{1−o(1)} ≤ f(K_n) ≤ (1/2+o(1))n (Bucić et al. arXiv:1809.01468; CCS 1984); trail version solved, path version not; f(K₃..K₆) = 2, 2, 3, 4 and min Σt = 5, 8, 14, 20 computed at creation, twice; no violation on ≤ 6 vertices. | `bash increasing_paths_sum.sh` |

### Calibration examples (known ground truth)

These dossiers have a *known* outcome and exist to regression-test the honesty pipeline:
the agent must discover the true status in the literature and label it correctly —
claimed proofs stay "under review", known refutations must be reproduced and verified,
and nothing gets upgraded past its artifacts.

| Directory | Ground truth | Expected honest outcome | Run |
|-----------|--------------|-------------------------|-----|
| [calibration-crouzeix](calibration-crouzeix/) | Crouzeix's conjecture received two independent claimed proofs in summer 2026 (Jin; Lorist–Schwenninger arXiv:2608.03841), under review. | Status "claimed / under review"; best peer-reviewed constant remains `1+√2`; numerics stay support-only. | `bash crouzeix.sh` |
| [calibration-casas-alvero](calibration-casas-alvero/) | Claimed proof (Ghosh, arXiv:2501.09272) under review; small degrees decidable per degree. | General claim "claimed / under review"; degrees `d ≤ 6` genuinely verified via sympy `proof_submit` as `PROOF-*` artifacts. | `bash casas_alvero.sh` |
| [calibration-perfect-mirsky](calibration-perfect-mirsky/) | Refuted for `n=5`: explicit doubly stochastic counterexample (Rivard–Mashreghi 2007, journal-only source). | `prove --disprove` finds, reproduces, and verifies the counterexample (`COUNTEREXAMPLE_VERIFIED` path); exact region `Θₙ` reported still unknown. | `bash perfect_mirsky.sh` |
| [calibration-brouwer](calibration-brouwer/) | Brouwer's Laplacian conjecture: claimed proof 2026 (Kothari–Tudose, arXiv:2606.12197), under review. | Status "claimed / under review"; exhaustive small-graph checks stay support-only. | `bash brouwer.sh` |
| [calibration-sendov](calibration-sendov/) | Sendov's conjecture: resolved August 2026 — complete AI-assisted proof, **Lean-verified** (Tao's blog digestion, 2026-08-12). Was slated as an open example; the status check at creation time caught the resolution. | Status "solved", with the formal verification named as such; interval spot checks stay support-only. Treating it as open fails calibration. | `bash sendov.sh` |
| [calibration-strassen-formal](calibration-strassen-formal/) | Correctness of Strassen's 7-product scheme (Laderman's 23-product 3×3 as stretch) — a finite system of ring identities, each closed by `ring` in Coq/Lean 4. Exercises the full `proof_submit` write → compile → error-feedback → resubmit loop. Backend: host `coqc`, or `lake` + `LEAN_PROJECT` (Mathlib), or a **containerized-Coq fallback** (verified: `docker run -v /tmp:/tmp coqorg/coq:8.20 coqc`) — no host prover needed. | ≥1 ACCEPTED Coq/Lean `proof_submit` (`PROOF-*` with `validates` edge); rejected compiles preserved as first-class attempts; numeric random-matrix checks stay support-only. | `bash strassen_formal.sh` |
| [calibration-steinberg](calibration-steinberg/) | Steinberg's conjecture (planar, no C₄/C₅ ⇒ 3-colorable) is REFUTED: Cohen-Addad–Hebdige–Kráľ–Li–Salgado, JCTB 122 (2017), arXiv:1604.05108 — a gadget construction presented in figures (~166 vertices reconstructed). | `prove --disprove` reconstructs the counterexample from the paper's gadgets (lemmas as transcription checksums), then machine-verifies all three properties — planarity, no 4-/5-cycles, 3-coloring UNSAT with a DRAT certificate — the `COUNTEREXAMPLE_VERIFIED` path; Bordeaux stays open. | `bash steinberg.sh` |
| [calibration-erdos-discrepancy](calibration-erdos-discrepancy/) | The Erdős discrepancy problem is SOLVED: Tao 2015 (arXiv:1509.05363, Discrete Analysis 2016), on the Polymath5 reduction; finite cases exact by SAT (max length 11 at C=1; 1160 at C=2, Konev–Lisitsa). | Status "solved" with correct attribution (Polymath5 = reduction, not the proof); C=1 reproduced with an UNSAT certificate; a 1160 sequence found by SAT; the C=3 exact maximum kept open (127,645 is multiplicative-only). | `bash erdos_discrepancy.sh` |
| [calibration-abc](calibration-abc/) | The abc conjecture has a PUBLISHED BUT CONTESTED proof claim: Mochizuki's IUT (PRIMS 2021) vs. the Scholze–Stix objection at Cor. 3.12; Joshi's arXiv claims unendorsed; the 2026 Lean effort (Project LANA) found the step unformalizable as written, no verdict. Primary sources are not on arXiv. | Status "contested claimed proof" — neither "proved" nor bare "open"; theorem layer (Stewart–Yu, Mason–Stothers) kept separate; record triple qualities (Reyssat q = 1.62991) recomputed exactly and certified. | `bash abc.sh` |
| [calibration-keller](calibration-keller/) | Keller's conjecture is RESOLVED with a dimension split: true n ≤ 6 (Perron 1940) and n = 7 (SAT + certified DRAT, arXiv:1910.03740; Lean 4 end-to-end 2026); false n ≥ 8 (Mackey 2002: explicit 256-clique in the Keller graph G₈,₂; Lagarias–Shor n ≥ 10). | Per-dimension status map (no unqualified "true"/"false"); Mackey's 256-clique reconstructed and all 32,640 pairs exactly verified (`COUNTEREXAMPLE_VERIFIED` for the n = 8 instance); the n = 7 SAT proofs cited with pedigree, not claimed re-run. | `bash keller.sh` |
| [calibration-ellipsoid-fitting](calibration-ellipsoid-fitting/) | The sharp n ~ d²/4 ellipsoid-fitting threshold (RS101 #6) was CLAIMED PROVED on 2026-08-10 — Misiakiewicz–Wen, arXiv:2608.10184, unrefereed, one week old at audit; theorem layer: n ≤ d²/C (2023, three proofs) and the sharp 1/4 for approximate fitting (Bandeira–Maillard, EJP 2025). | Status "claimed / under review" (neither "open" nor "proved"); normalizations reconciled; SDP feasibility experiments at d²/4 support-only, single rational instances certifiable exactly. | `bash ellipsoid_fitting.sh` |
| [calibration-group-spencer](calibration-group-spencer/) | Group Spencer (RS101 #2; regular representations of finite groups) CLAIMED RESOLVED by two independent June-2026 preprints (Bandeira–Bölcskei arXiv:2606.12181; Akbas–Sra arXiv:2606.16005), unrefereed; simple groups (BKMZ 2022) and abelian (Spencer) established; general Matrix Spencer still open. | Status "claimed / under review" with both preprints named; exhaustive, exactly certified sign minima for all groups of order ≤ 20–24; "two preprints agree" ≠ peer review. | `bash group_spencer.sh` |
| [calibration-sylvester-discrepancy](calibration-sylvester-discrepancy/) | RS101 #13 (disc(H_k) = √2·√(2^k) for odd k) is REFUTED for every odd k ≥ 9, true only for k ≤ 7 — via disc(H_k) = 2^k − 2ρ(RM(1,k)) and known nonlinearity records (Kavut–Yücel arXiv:0808.0684 at k = 9; Patterson–Wiedemann 1983 at k = 15); reported in arXiv:2504.20539 (Updates). | `prove --disprove` reconstructs an explicit x ∈ {±1}^512 with ‖H₉x‖_∞ = 28 < 32 and certifies it by an exact integer Walsh–Hadamard transform (`COUNTEREXAMPLE_VERIFIED`); disc(H₉) ∈ {24,26,28} kept open; #12 untouched. | `bash sylvester_discrepancy.sh` |
| [calibration-phase-retrieval](calibration-phase-retrieval/) | Injectivity at N = 4M−5 (RS101 #19): generic 4M−4 sufficient is a THEOREM (CEHV 2015); "4M−4 necessary" is FALSE (Vinzant 2015: 11 vectors in ℂ⁴); part (a) p_M < 1 CLAIMED by a 4-page "AI generated, human verified" note (arXiv:2606.17922, Jun 2026); part (b) p_M → 0 OPEN. | Four labels kept apart; Vinzant's certificate reproduced or an explicit non-injective instance certified exactly (rank-≤2 Hermitian kernel criterion, BCMN 2014 Lemma 9); Monte Carlo p_M as evidence for (b) only. | `bash phase_retrieval.sh` |
| [calibration-square-energy](calibration-square-energy/) | AIM spectralhypergraph 1.4: (1) min{S⁺,S⁻} ≥ n−1 (Elphick–Farber–Goldberg–Wocjan) was CLAIMED PROVED on 2026-07-20 (Liu–Tang–Zhang, arXiv:2607.18031, unrefereed — caught by the counter-audit after the first pass had it "open"); (2)–(4) the workshop's edge-addition monotonicity questions are REFUTED (Godsil's 9-vertex S⁺ decrease, arXiv:2303.11930; a 5-vertex S⁻ non-unimodality found at creation). | Part (1) "claimed / under review" with the 3n/4 theorem layer separate; parts (2)–(4) "refuted" with the exact certificates reproduced (`COUNTEREXAMPLE_VERIFIED` for the auxiliary claims only). | `bash square_energy.sh` |

Each directory has its own README with the full problem statement, a step-by-step
description of the workflow, and prerequisites.

---

## What these show

1. **Open problem → dossier** — `opentorus problem new --from-markdown notes.md`
   (or inline) turns a paper's stated problem into a typed, auditable dossier.
2. **Literature-backed proof attempt** — `opentorus prove PROBLEM-XXXX
   [--min-papers N] [--disprove]` runs a budgeted literature → draft → gap-fill
   loop; reports cite only local `PAPER-*` artifacts.
3. **Reproducible numerics** — the Simons example runs its `scripts/*.py` inside a
   pinned `python-sci` container (`opentorus env prepare`), recording `EXP-*`
   manifests.
4. **Honest reporting** — `opentorus problem report --lint` and `problem export
   --pdf` produce a report whose honesty linter flags overclaiming, and which
   never upgrades evidence into proof.

---

## Prerequisites

- **Docker** for the `python-sci` container (the numerical example).
- **A tool-calling model.** The scripts default to `gemma4:31b` on a local Ollama
  server (port 11434); override with `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL` /
  `OPENTORUS_PROVIDER` (`openai` also speaks to vLLM and other OpenAI-compatible
  servers — the API key may be any non-empty string there), or
  set `model.provider` / `model.name` / `model.base_url` to your own provider with
  `opentorus config set …`. The default `mock` provider is an offline smoke test
  only. Which model to pick is measured, not guessed — see below. On a remote
  Ollama server with slow model storage (a cluster's network filesystem), also set
  `opentorus config set model.keep_alive 45m`: a worker that pauses longer than
  Ollama's five-minute default between calls otherwise pays a cold reload — 25
  minutes for a 31B model, observed as a stall.

---

## Which model for which job

The scripts default to `gemma4:31b` because it did best in our own informal runs
of the calibration examples on local hardware. This is **not** a benchmark: a
handful of runs per model on a few examples, no statistical claim, and results
will differ on your hardware, your Ollama build, and your problems. Treat the
table as a starting point and re-check it yourself.

| Job | Model | What we saw |
|-----|-------|-------------|
| **Default** | **`gemma4:31b`** | Finished every task we gave it, labelled the 2026 Casas-Alvero and Crouzeix proof claims as *claimed, not peer-reviewed*, and had its verifier submissions accepted throughout. |
| Fast formal verification only | `qwen3.8:latest` | Much faster on the pure formalization example, but did not finish the open-ended ones inside our time budget, so it left no report to review. |
| Also workable | `nemotron-3-super`, `qwen3.6:27b`, `mistral-medium-3.5` | Reached full coverage on the formalization example; each was weaker than `gemma4:31b` on at least one open-ended example. |
| Did not get far for us | `gpt-oss:120b`, `deepseek-r1:70b`, `glm-4.7-flash`, `qwen3-vl:32b`, `qwen3-coder`, `muse-glimmer:30b` | Never reached the formal path, or produced no deliverable, in the runs we did. |

Three observations worth carrying over to your own model choices:

1. **Parameter count predicted little.** In our runs, 27–31 B models did better
   than everything above 100 B, and both sibling pairs inverted (`gemma4:31b` did
   better than `gemma4:26b`, but `qwen3.6:27b` better than `qwen3.6:35b`). What
   seemed to separate them was willingness to call a tool instead of writing more
   prose, and discipline in keeping to a format.
2. **Formal skill ≠ research skill.** A model that does well on the formalization
   example (fixed target, one tool, four identities) can still fail an open-ended
   dossier where it must decide *what* to do, run experiments, and finish in time.
   Try both before settling on a model.
3. **A single run tells you very little.** The same model produced 3 verifier
   submissions in one run and 0 in the next on an identical task. Repeat a few
   times before drawing conclusions.

---

## Set expectations

| Expectation | Reality |
|-------------|---------|
| "Solve every problem in a survey autonomously" | Scope one problem per `prove` run; surveys are for reading and prioritizing. |
| `opentorus research "…"` = general autonomous prover | Fixed loop: local papers + counterexample-search experiments + journal. |
| `opentorus problem report` writes the analysis | It assembles from existing dossier artifacts; run the agent first. |
| Evidence ⇒ proven | The status ladder stops at human review; a verified claim needs a verification artifact. |

For interactive steering (closest to a chat session): `opentorus chat`.
