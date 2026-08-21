#!/usr/bin/env bash
# ============================================================================
# OpenTorus CALIBRATION example — Formal verification of fast matrix
# multiplication schemes (Coq / Lean 4)
#
# KNOWN ground truth (see README.md): Strassen's 7-product scheme (1969) and
# Laderman's 23-product scheme (1976) are correct. This example exists to
# exercise the FORMAL round-trip end to end: the agent writes Coq/Lean source,
# submits it via proof_submit, reads the compiler's error feedback, fixes the
# source, and resubmits until the checker accepts. Scheme correctness is a
# finite system of ring identities — `ring` closes each goal mechanically, so
# the challenge is exactly the write/compile/fix loop, not deep mathematics.
#
# Backend selection (first match wins):
#   1. host `coqc`                          -> coq
#   2. host `lake` + $LEAN_PROJECT set      -> lean4 (Mathlib project for `ring`)
#   3. docker                                -> containerized Coq (coqorg/coq:8.20)
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./strassen_formal.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

TARGET="${1:-PROBLEM-0001}"

# --- 1. Fresh workspace -----------------------------------------------------
rm -rf .opentorus
rm -f notes.md
opentorus init

# --- 2. Model & agent configuration -----------------------------------------
opentorus config set model.provider "${OPENTORUS_PROVIDER:-ollama}"
opentorus config set model.name "${OPENTORUS_MODEL:-gemma4:31b}"
opentorus config set model.base_url "${OPENTORUS_BASE_URL:-http://localhost:11434}"
opentorus config set model.timeout_seconds 2400
opentorus config set agent.style autonomous
opentorus config set agent.max_steps inf
opentorus config set agent.prove_gap_fill_max_steps inf
opentorus config set permissions.mode trusted

# --- 2b. Formal backend ------------------------------------------------------
if command -v coqc >/dev/null 2>&1; then
  opentorus config set tools.verifiers.coq true
  BACKEND=coq
elif command -v lake >/dev/null 2>&1 && [ -n "${LEAN_PROJECT:-}" ]; then
  opentorus config set tools.verifiers.lean true
  opentorus config set tools.verifiers.lean_command "lake --dir ${LEAN_PROJECT} env lean"
  BACKEND=lean4
elif command -v docker >/dev/null 2>&1; then
  # Containerized Coq: the verifier writes the source under /tmp (or $TMPDIR)
  # and appends the file path to this command; the mounts make it visible.
  MOUNTS="-v /tmp:/tmp"
  if [ -n "${TMPDIR:-}" ] && [ "${TMPDIR}" != "/tmp" ]; then
    MOUNTS="${MOUNTS} -v ${TMPDIR}:${TMPDIR}"
  fi
  # `coqtop -batch -load-vernac-source` CHECKS without compiling: coqc would write
  # proof.vo/.glob next to the source, and the container's uid cannot write into the
  # host-owned temp dir (every submission failed "Permission denied"). Batch-loading
  # needs read access only, and still exits non-zero on a real proof error.
  opentorus config set tools.verifiers.coq true
  opentorus config set tools.verifiers.coq_command \
    "docker run --rm ${MOUNTS} coqorg/coq:8.20 coqtop -batch -load-vernac-source"
  BACKEND=coq
else
  echo "ERROR: no formal backend available. Install coqc, provide lake + LEAN_PROJECT" >&2
  echo "       (a Mathlib-enabled Lean project), or install docker for the Coq fallback." >&2
  exit 1
fi
echo "Formal backend: ${BACKEND}"

# --- 3. Numerical experiment environment ------------------------------------
# Numeric sanity checks of the schemes on random matrices (support-only).
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers -------------------------------------------------------
# Both contain explicit rank-23 3x3 schemes (for the stretch goal).
opentorus paper add https://arxiv.org/abs/2604.27645
opentorus paper add https://arxiv.org/abs/2601.05272

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Machine-checked correctness of fast matrix multiplication schemes

**Ground-truth context.** Strassen (1969) multiplies two $2\times 2$ matrices with 7
products; Laderman (1976) multiplies $3\times 3$ with 23. Both are correct — the goal of
this dossier is not discovery but **machine-checked verification through the formal
backend**, exercising the full write → compile → fix → resubmit loop via `proof_submit`.

**The scheme to verify (Strassen).** With
$p_1=(a_{11}+a_{22})(b_{11}+b_{22})$, $p_2=(a_{21}+a_{22})b_{11}$,
$p_3=a_{11}(b_{12}-b_{22})$, $p_4=a_{22}(b_{21}-b_{11})$,
$p_5=(a_{11}+a_{12})b_{22}$, $p_6=(a_{21}-a_{11})(b_{11}+b_{12})$,
$p_7=(a_{12}-a_{22})(b_{21}+b_{22})$, the product $C = AB$ satisfies
$c_{11}=p_1+p_4-p_5+p_7$, $c_{12}=p_3+p_5$, $c_{21}=p_2+p_4$, $c_{22}=p_1-p_2+p_3+p_6$.
Correctness is the statement that these four identities hold for all values of the eight
variables over a commutative ring — four polynomial identities, each provable by `ring`.

**Task ladder.**
1. Numeric sanity check (support-only): exp_new/exp_run a script multiplying random
   integer matrices via the scheme and comparing with direct multiplication.
2. claim_new: "Strassen's 7-product scheme computes the 2x2 matrix product."
3. **Formal verification**: write __BACKEND__ source proving the four identities and
   submit via proof_submit(backend="__BACKEND__", claim_id=...). On REJECTED, read the
   compiler output, fix the source, resubmit. Iterate until ACCEPTED. One file with four
   lemmas is fine.
4. Stretch goal: the Laderman 23-product scheme for $3\times 3$ (nine identities; take
   the explicit scheme from the parsed PAPER-* artifacts; one lemma per output entry
   keeps error feedback local).

**Formal template (Coq flavor).** A single identity looks like:

```
Require Import ZArith.
Open Scope Z_scope.
Lemma strassen_c12 :
  forall a11 a12 a21 a22 b11 b12 b21 b22 : Z,
    a11*(b12-b22) + (a11+a12)*b22 = a11*b12 + a12*b22.
Proof. intros; ring. Qed.
```

For Lean 4 (Mathlib): `import Mathlib.Tactic.Ring` and close each goal with `ring`.

**Honesty requirements.** The numeric experiment never verifies anything — only an
ACCEPTED proof_submit does. The claim's status still changes only through the gated
update after the formal artifact exists. Report exactly which identities are
machine-checked and which (Laderman entries, if unfinished) are not.
NOTES
# `sed -i` without a backup suffix is GNU-only: BSD/macOS sed reads the next word as
# the suffix and then chokes on the filename ("extra characters at the end of n
# command"), which killed this driver five seconds in. Write through a temp file so
# the substitution is portable.
sed "s/__BACKEND__/${BACKEND}/g" notes.md > notes.md.tmp && mv notes.md.tmp notes.md
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Verify formally ------------------------------------------------------
# `prove` gates on the honesty linter: a report that still overclaims exits non-zero.
# That is a finding to read, not a crash — but under `set -e` it aborted this driver
# right here, before the report/verdict/PDF steps below ever ran. Keep the signal,
# finish the workflow, and exit with it at the end.
PROVE_RC=0
opentorus --verbose prove "${TARGET}" --min-papers 2 || PROVE_RC=$?

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint || true   # advisory: warnings are findings to read, not a reason to skip the verdict
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
echo "Calibration check: at least one ACCEPTED ${BACKEND} proof_submit (PROOF-* with"
echo "'validates' edge); rejected attempts preserved; numeric checks stay support-only."

exit "${PROVE_RC}"
