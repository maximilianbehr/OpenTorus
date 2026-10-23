"""Textual rules for Coq sources, decided without running ``coqc``.

The Coq analogue of :mod:`opentorus.research.verifiers.lean_rules`: ``coqc`` exits 0
on a file whose proofs end in ``Admitted``, that declares ``Axiom``s, or that loads an
ML plugin. The gate refuses those tokens outside comments and strings, then appends
``Print Assumptions <thm>.`` behind an unpredictable marker and reads only what
follows it: a theorem is accepted only when it is *closed under the global context*.
"""

from __future__ import annotations

import re
import secrets

# Words that leave a proof unfinished, add an assumption, or make coqc load/run code,
# write files, or switch off a kernel check. Matched as whole words on comment- and
# string-blanked code.
FORBIDDEN_WORDS: frozenset[str] = frozenset(
    {
        "Admitted",
        "admit",
        "give_up",
        "Axiom",
        "Axioms",
        "Parameter",
        "Parameters",
        "Conjecture",
        "Load",
        "Drop",
        "Redirect",
        "Extraction",
        "Cd",
        "Declare",  # Declare ML Module
        "Bypass",
        "bypass_check",
    }
)
# ``Unset <X> Checking`` switches off the guard / positivity / universe checker.
_UNSET_CHECKING = re.compile(r"\b(?:Unset|Local\s+Unset|Global\s+Unset)\s+\w+\s+Checking\b")
_ADD_PATH = re.compile(r"\bAdd\s+(?:Rec\s+)?(?:LoadPath|ML\s+Path)\b")

_DECL_RE = re.compile(
    r"\b(?:Theorem|Lemma|Corollary|Proposition|Fact|Remark|Example)\s+([A-Za-z_][\w']*)"
)
_SCOPE_RE = re.compile(r"\b(Module(?:\s+Type)?|Section|End)\s+([A-Za-z_][\w']*)")


class CoqSourceError(ValueError):
    """The source contains a construct the gate cannot read unambiguously."""


def coq_code(source: str) -> str:
    """``source`` with ``(* … *)`` comments (nested) and string literals blanked."""
    out = list(source)
    n = len(source)
    k = 0

    def blank(a: int, b: int) -> None:
        for i in range(a, b):
            if out[i] != "\n":
                out[i] = " "

    while k < n:
        c = source[k]
        if c == "(" and k + 1 < n and source[k + 1] == "*":
            start, depth = k, 1
            k += 2
            while k < n and depth:
                if source.startswith("(*", k):
                    depth += 1
                    k += 2
                elif source.startswith("*)", k):
                    depth -= 1
                    k += 2
                elif source[k] == '"':
                    # Coq lexes strings inside comments too.
                    end = _string_end(source, k)
                    if end is None:
                        raise CoqSourceError("unterminated string inside a comment")
                    k = end
                else:
                    k += 1
            if depth:
                raise CoqSourceError("comment opened with (* and never closed")
            blank(start, k)
        elif c == '"':
            end = _string_end(source, k)
            if end is None:
                raise CoqSourceError("unterminated string literal")
            blank(k, end)
            k = end
        else:
            k += 1
    return "".join(out)


def _string_end(source: str, k: int) -> int | None:
    """Offset after the string starting at ``k`` (``""`` is an escaped quote)."""
    i = k + 1
    while i < len(source):
        if source[i] == '"':
            if i + 1 < len(source) and source[i + 1] == '"':
                i += 2
                continue
            return i + 1
        i += 1
    return None


def forbidden_token(source: str) -> str | None:
    """The first forbidden construct in ``source`` (outside comments/strings)."""
    try:
        code = coq_code(source)
    except CoqSourceError as exc:
        return str(exc)
    for word in re.findall(r"[A-Za-z_][\w']*", code):
        if word in FORBIDDEN_WORDS:
            return word
    if _UNSET_CHECKING.search(code):
        return "Unset … Checking"
    if _ADD_PATH.search(code):
        return "Add LoadPath / ML Path"
    return None


def theorem_names(source: str) -> list[str]:
    """Qualified names of the proved declarations (``Module`` scopes tracked)."""
    try:
        code = coq_code(source)
    except CoqSourceError:
        return []
    events: list[tuple[int, str, str]] = []
    for m in _SCOPE_RE.finditer(code):
        events.append((m.start(), m.group(1).split()[0], m.group(2)))
    for m in _DECL_RE.finditer(code):
        events.append((m.start(), "decl", m.group(1)))
    events.sort(key=lambda e: e[0])
    stack: list[tuple[str, str]] = []
    names: list[str] = []
    for _pos, kind, arg in events:
        if kind in ("Module", "Section"):
            stack.append((kind, arg))
        elif kind == "End":
            if stack:
                stack.pop()
        else:
            prefix = ".".join(name for k, name in stack if k == "Module")
            qualified = f"{prefix}.{arg}" if prefix else arg
            if qualified not in names:
                names.append(qualified)
    # A theorem declared inside a still-open Section is renamed nowhere, but one in a
    # closed Module is reachable only qualified — which is what is listed.
    return names


def fresh_marker() -> str:
    return "opentorus_report_" + secrets.token_hex(12)


def report_commands(marker: str, thms: list[str], *, type_of: str | None = None) -> str:
    """``Locate <marker>.`` (prints the unknown name), then one ``Print Assumptions``
    per theorem, then optionally ``Check <thm>.`` for the statement-fidelity probe."""
    text = f"\nLocate {marker}.\n"
    text += "".join(f"Print Assumptions {t}.\n" for t in thms)
    if type_of is not None:
        text += f"Set Printing All.\nCheck {type_of}.\n"
    return text


class CoqReport:
    def __init__(self, assumptions: dict[str, list[str]], type_text: str | None) -> None:
        self.assumptions = assumptions
        self.type_text = type_text


def parse_report(
    output: str, marker: str, thms: list[str], *, type_of: str | None = None
) -> CoqReport | None:
    """Read only what follows the line naming ``marker``.

    Each theorem's block must be ``Closed under the global context`` or an
    ``Axioms:`` list; the ``Check`` block (if requested) runs to the end.
    """
    if output.count(marker) != 1:
        return None
    lines = output.splitlines()
    idx = next((i for i, ln in enumerate(lines) if marker in ln), None)
    if idx is None:
        return None
    rest = [ln.rstrip() for ln in lines[idx + 1 :]]
    pos = 0
    assumptions: dict[str, list[str]] = {}
    for i, thm in enumerate(thms):
        while pos < len(rest) and not rest[pos].strip():
            pos += 1
        if pos >= len(rest):
            return None
        head = rest[pos].strip()
        pos += 1
        if head == "Closed under the global context":
            assumptions[thm] = []
            continue
        if not head.startswith("Axioms:"):
            return None
        items: list[str] = []
        last = i == len(thms) - 1 and type_of is None
        while pos < len(rest) and rest[pos].strip():
            line = rest[pos]
            if not last and (
                line.strip() == "Closed under the global context"
                or line.strip().startswith("Axioms:")
            ):
                break
            if not line.startswith(" ") and ":" in line:
                items.append(line.split(":", 1)[0].strip())
            pos += 1
        assumptions[thm] = items or ["<unparsed assumption>"]
    remaining = "\n".join(rest[pos:]).strip()
    if type_of is None:
        return CoqReport(assumptions, None) if not remaining else None
    if not remaining:
        return None
    return CoqReport(assumptions, remaining)


def extract_statement(frozen: str) -> str | None:
    """From the first proved declaration keyword to the end of its statement (``.``)."""
    try:
        code = coq_code(frozen)
    except CoqSourceError:
        return None
    m = _DECL_RE.search(code)
    if m is None:
        return None
    end = re.search(r"\.(?=\s|$)", code[m.end() :])
    if end is None:
        return None
    return frozen[m.start() : m.end() + end.end()]


def contains_statement(candidate: str, statement: str) -> bool:
    try:
        stmt = " ".join(coq_code(statement).split())
        return stmt in " ".join(coq_code(candidate).split())
    except CoqSourceError:
        return False


def frozen_objection(frozen: str) -> str | None:
    """Why ``frozen`` cannot be a frozen Coq statement: it must parse, declare one
    theorem, and end its proof with ``Admitted.`` and nothing else forbidden."""
    try:
        code = coq_code(frozen)
    except CoqSourceError as exc:
        return str(exc)
    stripped = re.sub(r"\bAdmitted\s*\.", " ", code)
    bad = forbidden_token(stripped)
    if bad:
        return f"forbidden token {bad!r}"
    if extract_statement(frozen) is None:
        return "no `Theorem/Lemma name : … .` statement found"
    if len(theorem_names(frozen)) != 1:
        return "a frozen file must declare exactly one theorem"
    return None


__all__ = [
    "CoqSourceError",
    "FORBIDDEN_WORDS",
    "coq_code",
    "contains_statement",
    "extract_statement",
    "forbidden_token",
    "fresh_marker",
    "frozen_objection",
    "parse_report",
    "report_commands",
    "theorem_names",
]
