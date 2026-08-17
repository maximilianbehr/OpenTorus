# Two small restricted Boltzmann machines: $RBM_{4,3}$ universality, $\mathcal D(RBM_{3,1})$

> **Fixed-instance dossier** (two specific models — not a campaign; no primary-claim
> designation, no `problem verdict` gate). Deliverable: an honest status sketch with the
> exact facts machine-checked and the numerics labelled as evidence.
>
> Source: [AIM Problem List *Boltzmann machines*](http://aimpl.org/boltzmann/1/)
> (ed. T. Merkh, AIM workshop Sept 2018; http only), Problems 1.1 [G. Montúfar] and 1.2.

## The problems

1. Does the closure of $RBM_{4,3}$ (4 visible, 3 hidden binary units; 19 parameters)
   fill the 15-simplex, i.e. is it a universal approximator? Three hidden units are
   necessary; six suffice; the page says simulations *suggest* three do.
2. What is $\sup_p \inf_{q \in RBM_{3,1}} D(p\|q)$ — the maximum KL divergence from the
   mixture of two product distributions on three bits? Known $\le 1$ bit; the first open
   case in Montúfar's review, with a conjectured value $-\tfrac34\log_2(2\sqrt3-3)
   \approx 0.8306$ bits.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Both open.** The bounds and adjacent solved cases ($\mathcal D_{3,2} = 1/2$ bit,
$RBM_{3,3}$ full, $RBM_{4,6}$ universal, $\dim RBM_{4,3} = 15$) are in Montúfar's review
([arXiv:1806.07066](https://arxiv.org/abs/1806.07066)), Seigal–Montúfar
([arXiv:1709.05276](https://arxiv.org/abs/1709.05276)), Montúfar–Rauh–Ay
([arXiv:1406.3140](https://arxiv.org/abs/1406.3140)) and Montúfar–Rauh
([arXiv:1508.03606](https://arxiv.org/abs/1508.03606)); the page's "$m \ge 7$
sufficient" is the outdated 2010 bound. Creation-time computation: the conjectured
$\mathcal D_{3,1}$ value is reproduced to seven digits at the uniform distribution on the
even-parity strings, and nothing larger was found; for $RBM_{4,3}$, exact
maximum-likelihood fits reach machine precision on parity and generic targets but
**stall at a positive residual on the soft-parity family** $p_a = (1 + a(-1)^{|v|})/16$
(≈ 0.077 bits at $a = 0.8$, ≈ 0.042 at $a = 0.5$, with diverging parameters; robust across
five optimizers and the counter-audit's independent implementation) — numerical evidence
*against* the fullness the page's simulations suggested; not a proof, and the numerics
certify only the *upper* bound on the inner infimum, so no lower bound on
$\mathcal D_{4,3}$ follows without global optimality.

## What this runs

`rbm_universality_divergence.sh`: fresh workspace → config (timeout 2400s) → container
with numpy/scipy/sympy → five audit-verified papers → dossier → `prove --min-papers 4`
→ report + lint → PDF.

The instance program: certify the inner projection of the parity target onto
$\mathcal M_{3,2}$ exactly (`proof_submit`, sympy — the optimum has $\sqrt3$ structure);
bound the outer supremum via the four log-linear polyhedra of
Allman–Rhodes–Sturmfels–Zwiernik ([arXiv:1305.0539](https://arxiv.org/abs/1305.0539));
re-run the $RBM_{4,3}$ fits with validated optimizers and turn a persistent stall into a
limit/tropical obstruction — or a successful fit into an explicit approximation family.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: a machine-checked inner-projection value, a numerically found
supremum, reproduced or refuted stalls — `NUMERICAL_EVIDENCE` and at most a lemma; the
conjectured $\mathcal D_{3,1}$ stays a conjecture until the outer supremum is bounded.
$RBM_{3,1} \ne RBM_{3,2}$; divergences in bits.

## Selected references

- G. Montúfar, *Restricted Boltzmann machines: introduction and review*:
  [arXiv:1806.07066](https://arxiv.org/abs/1806.07066).
- A. Seigal, G. Montúfar, *Mixtures and products in two graphical models*:
  [arXiv:1709.05276](https://arxiv.org/abs/1709.05276).
- G. Montúfar, J. Rauh, N. Ay, *Expressive power and approximation errors of restricted
  Boltzmann machines*: [arXiv:1406.3140](https://arxiv.org/abs/1406.3140).
- G. Montúfar, J. Rauh, *Hierarchical models as marginals of hierarchical models*:
  [arXiv:1508.03606](https://arxiv.org/abs/1508.03606).
- E. S. Allman, J. A. Rhodes, B. Sturmfels, P. Zwiernik, *Tensors of nonnegative rank two*:
  [arXiv:1305.0539](https://arxiv.org/abs/1305.0539).
