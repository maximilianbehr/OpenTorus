# Summary for PROBLEM-0001

## Collected Observations

- **PAPER-0001** (arXiv:2604.16075) – Introduces MINBERR and perturbed MINBERR-NE, showing that Gaussian perturbations enable κ‑independent backward error rates for general matrices (O(log n/k)).
- **PAPER-0002** (arXiv:1506.03296) – Experimental comparison of randomized Kaczmarz, Gaussian LS, etc.; illustrates practical performance but does not provide universal backward error guarantees.
- **PAPER-0003** (arXiv:1903.07971) – Studies inexact randomized iterative methods for linear systems; convergence analysis under controlled inexactness, relevant to randomness and backward error.
- **PAPER-0004** (arXiv:2410.11115) – Sketched Iterative and Recursive Refinement (SIRR) achieves κ‑independent backward error improvement via randomized sketching plus refinement.
- **PAPER-0005** (arXiv:1609.01321) – Discusses backward error analysis as a general framework for perturbation methods.
- **PAPER-0006** (arXiv:2602.10424) – Analyzes subspace embedding and sketching for LS problems; bounds depend on condition number and ε‑distortion.
- **PAPER-0007** (arXiv:2204.01653) – Survey of randomized block Kaczmarz and coordinate descent methods involving Gaussian sketches.
- **PAPER-0015** (arXiv:2605.09211) – Provides a variational formulation for backward error in LS, establishing O(log n/k) rates with Gaussian perturbations.
- **PAPER-0016** (arXiv:2311.04362) – Proves forward stability of iterative sketching, achieving backward error comparable to QR without extra perturbation.

## Known Results Linked to the Problem

- *Result 1* (from PAPER-0015): MINBERR‑NE with Gaussian perturbations attains O(log n/k) backward error independent of κ(A). (`KR-0001`)

## Relevant Papers Added to Dossier

- `RELP-0016`: PAPER-0001 – Perturbed MINBERR‑NE and Gaussian perturbations.
- `RELP-0017`: PAPER-0004 – SIRR method with κ‑independent backward error.
- `RELP-0018`: PAPER-0016 – Forward stability of iterative sketching without extra perturbation.

These observations and results form the basis for further investigation into whether randomness is necessary for κ‑independent backward error convergence in general (non‑PSD) linear systems.