# Campaign: The Lonely Runner conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — every number of runners; individual $k$ are
> internal tools. The driver designates the primary claim deterministically.

## The problem

$k+1$ runners circle a unit track at pairwise distinct constant speeds. The conjecture
(Wills 1967, Cusick 1974): each runner is, at some moment, at circular distance at least
$\frac{1}{k+1}$ from every other — equivalently, for any distinct nonzero integer speeds
$v_1..v_k$ there is a time $t$ with $\lVert t v_i\rVert \ge \frac{1}{k+1}$ for all $i$.
The speeds $\{1,\dots,k\}$ show the bound is tight.

## Status audit (2026-08-14, fresh web check)

**Open in general — with a 2025/26 landslide in low dimensions** (audit amended
2026-08-15 after an independent cross-check). Settled for up to **13 runners**
($k \le 12$), the cases 8–13 all recent *computer-assisted preprints*: Rosenfeld's new
computational framework settled 8 ([arXiv:2509.14111](https://arxiv.org/abs/2509.14111)),
a sieve strengthening settled 9 and 10
([arXiv:2511.22427](https://arxiv.org/abs/2511.22427)) with 9 also settled independently
and concurrently ([arXiv:2512.01912](https://arxiv.org/abs/2512.01912)), and 11–13
followed ([arXiv:2604.23906](https://arxiv.org/abs/2604.23906)); 7 was Barajas–Serra 2008
([arXiv:0710.4495](https://arxiv.org/abs/0710.4495)). That makes this campaign unusual:
the frontier method is *itself computational*, so the instance program can genuinely
engage the state of the art rather than orbit it.

## What this runs

`lonely_runner.sh` follows the campaign template: fresh workspace → config (timeout
2400s) → container with z3 → four audit-verified papers → dossier → **driver-created
primary claim** + `verdict --set-primary` → `prove --min-papers 5` → report + lint →
`problem verdict` → PDF.

Dual track: the refutation side exploits that per speed set the maximal loneliness is
*exactly computable* (piecewise linear, rational breakpoints) — every candidate is a
finite certificate for `proof_submit`. The proof track reproduces the Rosenfeld-style
reduction pipeline on the smallest open $k$ and certifies eliminated speed-set classes
as finite checks.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Run

```bash
bash lonely_runner.sh
```

## Honesty note

Realistic outcomes: a status sketch that gets the fast-moving 2025/26 literature right,
exact loneliness certificates for structured speed families, one reproduced-and-certified
elimination step from the modern framework — `COMPUTATIONAL_EVIDENCE`, not a resolution.
A counterexample would have to live at $k \ge 13$ and would be exactly verifiable; the
tightness of $\{1..k\}$ is the reason optimism and caution coexist here.

## Selected references

- J. M. Wills (1967); T. W. Cusick (1974) — the conjecture's origins.
- J. Barajas, O. Serra (2008), [arXiv:0710.4495](https://arxiv.org/abs/0710.4495) — 7 runners.
- M. Rosenfeld (2025), [arXiv:2509.14111](https://arxiv.org/abs/2509.14111) — 8 runners.
- [arXiv:2511.22427](https://arxiv.org/abs/2511.22427) — 9 and 10 runners;
  [arXiv:2512.01912](https://arxiv.org/abs/2512.01912) — 9 runners, independent and
  concurrent (both 2025).
- Sungkawichai–Trakulthongchai (2026), [arXiv:2604.23906](https://arxiv.org/abs/2604.23906)
  — 11, 12, and 13 runners ($k \in \{10,11,12\}$).
