"""Textual rules for Lean 4 sources, decided without running Lean.

A Lean file that elaborates with exit code 0 is not a proof: ``sorry`` is a warning,
a user ``axiom`` is legal, ``native_decide`` trusts the compiler, and ``#eval`` /
``run_cmd`` run arbitrary code on the host while the file elaborates (spawning
processes, writing files, printing anything into the output the verdict is read
from). This module is the pre-flight half of the Lean gate:

* :func:`lean_code` blanks comments and string literals (so ``-- no sorry left`` is
  not an unfinished proof) and *refuses* every construct where this lexer and Lean's
  could disagree, instead of guessing;
* :func:`forbidden_token` names the first banned token: ``sorry``, ``native_decide``,
  a user ``axiom``, ``set_option pp.*``/``debug.*``, and every code-execution or
  syntax-extension word (:data:`EXEC_WORDS`);
* :func:`theorem_names` finds the declarations whose axioms the gate audits with an
  appended ``#print axioms`` behind an unpredictable marker
  (:func:`fresh_marker`, :func:`parse_report`).

The rules are a port of the open-math-harness Lean protocol
(``interfaces/lean/src/rules.rs``, ``program-files/lean/src/verify.rs``).
"""

from __future__ import annotations

import re
import secrets

# The three foundational Lean axioms a proof may depend on. Anything else — and in
# particular ``sorryAx`` (an unfinished proof) or ``Lean.ofReduceBool``
# (``native_decide``) — rejects.
TRUSTED_AXIOMS: frozenset[str] = frozenset({"propext", "Classical.choice", "Quot.sound"})

# Words that make Lean run code, change the syntax, or reach the meta-programming and
# IO libraries while it elaborates. A proof needs none of them. Elaborated code can
# print anything to the output the verdict is read from, add tokens that make the text
# read differently than :func:`lean_code` reads it, or spawn processes on the host.
# Harness list ``interfaces/lean/src/rules.rs`` EXEC_WORDS, verbatim.
EXEC_WORDS: frozenset[str] = frozenset(
    {
        "#exit",
        "#guard",
        "#html",
        "#widget",
        "#sample",
        "#test",
        "run_cmd",
        "run_elab",
        "run_meta",
        "run_tac",
        "by_elab",
        "syntax",
        "macro",
        "macro_rules",
        "elab",
        "elab_rules",
        "declare_syntax_cat",
        "notation",
        "notation3",
        "infix",
        "infixl",
        "infixr",
        "prefix",
        "postfix",
        "binder_predicate",
        "initialize",
        "builtin_initialize",
        "simproc",
        "dsimproc",
        "simproc_decl",
        "dsimproc_decl",
        "command_elab",
        "term_elab",
        "tactic",
        "delab",
        "app_unexpander",
        "implemented_by",
        "extern",
        "unsafe",
        "Lean",
        "Mathlib",
        "Aesop",
        "Batteries",
        "Qq",
        "IO",
        "EIO",
        "BaseIO",
        "println!",
        "eprintln!",
        "asTask",
    }
)

# Options a candidate may not set: ``pp.*`` would change the ``pp.all`` type the
# statement-fidelity probe compares, ``debug.*`` includes skipping the kernel check.
BANNED_OPTION_ROOTS: frozenset[str] = frozenset({"pp", "debug"})

# Library roots a header may ``import``; anywhere else they are EXEC_WORDS.
IMPORTABLE: frozenset[str] = frozenset({"Lean", "Mathlib", "Aesop", "Batteries", "Qq"})

# The command put right after a frozen preamble (statement fidelity): Lean parses what
# follows as a new command, so a candidate cannot continue the preamble's last
# declaration (``def f n := n`` continued with ``+ 1``).
SEPARATOR = '#print "opentorus: the frozen preamble ends here"'

MAX_SOURCE_BYTES = 256 * 1024


class LeanSourceError(ValueError):
    """The source contains a construct the gate cannot read unambiguously."""


_AMBIGUOUS = "string or character literal the checker cannot read unambiguously"
_OPEN_COMMENT = "comment opened with /- and never closed with -/"
_OPEN_NAME = "name opened with « and never closed with »"


def is_id_rest(c: str) -> bool:
    """Lean's ``isIdRest``: characters that continue an identifier."""
    v = ord(c)
    letter_like = (
        (0x3B1 <= v <= 0x3C9 and v != 0x3BB)
        or (0x391 <= v <= 0x3A9 and v not in (0x3A0, 0x3A3))
        or 0x3CA <= v <= 0x3FB
        or 0x1F00 <= v <= 0x1FFE
        or 0x2100 <= v <= 0x214F
        or 0x1D49C <= v <= 0x1D59F
    )
    subscript = 0x2080 <= v <= 0x2089 or 0x2090 <= v <= 0x209C or 0x1D62 <= v <= 0x1D6A
    subscript = subscript or v == 0x2C7C
    return (c.isascii() and c.isalnum()) or c in "_'!?" or letter_like or subscript


def lean_code(source: str) -> str:
    """``source`` with comments and string literals blanked to spaces.

    Nothing moves (newlines are kept), so offsets in the result are offsets in the
    source. Raises :class:`LeanSourceError` for every place this lexer might read
    the text differently from Lean: a string opened right after an identifier
    character, ``'``, ``\\`` or ``#`` (raw, interpolated, char-literal strings), a
    string containing ``\\`` or ``{``, an unterminated string or ``/-`` comment, an
    unclosed ``«`` name, and ``'``/``\\`` right before ``«``, ``--`` or ``/-``.
    Legitimate proofs need none of these. Escaped identifiers ``«…»`` stay visible,
    so a banned name cannot hide in them.
    """
    out = list(source)
    n = len(source)

    def at(k: int) -> str | None:
        return source[k] if 0 <= k < n else None

    def blank(start: int, end: int) -> None:
        for i in range(start, end):
            if out[i] != "\n":
                out[i] = " "

    k = 0
    while k < n:
        c = source[k]
        prev = at(k - 1)
        quote_or_escape = prev in ("'", "\\")
        opens_comment = (c == "-" and at(k + 1) == "-") or (c == "/" and at(k + 1) == "-")
        if (opens_comment or c in ("«", '"')) and quote_or_escape:
            raise LeanSourceError(_AMBIGUOUS)
        if c == "-" and at(k + 1) == "-":
            start = k
            while k < n and source[k] != "\n":
                k += 1
            blank(start, k)
        elif c == "/" and at(k + 1) == "-":
            start, depth = k, 1
            # Lean reads ``/--`` and ``/-!`` as one token, so ``/--/`` opens a doc
            # comment rather than closing an empty one.
            k += 3 if at(k + 2) in ("-", "!") else 2
            while k < n and depth > 0:
                if source[k] == "-" and at(k + 1) == "/":
                    depth -= 1
                    k += 2
                elif source[k] == "/" and at(k + 1) == "-":
                    depth += 1
                    k += 2
                else:
                    k += 1
            if depth > 0:
                raise LeanSourceError(_OPEN_COMMENT)
            blank(start, k)
        elif c == '"':
            if prev is not None and (is_id_rest(prev) or prev == "#"):
                raise LeanSourceError(_AMBIGUOUS)
            start = k
            k += 1
            while True:
                ch = at(k)
                if ch is None or ch in ("\\", "{"):
                    raise LeanSourceError(_AMBIGUOUS)
                if ch == '"':
                    break
                k += 1
            k += 1
            blank(start, k)
        elif c == "«":
            while k < n and source[k] != "»":
                k += 1
            if k == n:
                raise LeanSourceError(_OPEN_NAME)
        else:
            k += 1
    return "".join(out)


def words(code: str) -> list[tuple[str, int]]:
    """Maximal runs of identifier characters (a leading ``#`` kept), with end offsets."""
    out: list[tuple[str, int]] = []
    start: int | None = None
    for i, c in [*enumerate(code), (len(code), " ")]:
        if start is not None:
            if not is_id_rest(c):
                if not (i == start + 1 and code[start] == "#"):
                    out.append((code[start:i], i))
                start = i if c == "#" else None
        elif is_id_rest(c) or c == "#":
            start = i
    return out


def exec_word(code: str) -> str | None:
    """The first word in ``code`` that makes Lean run code or alter what is read."""
    ws = words(code)
    in_import = False
    for idx, (word, end) in enumerate(ws):
        start = end - len(word)
        if idx > 0:
            prev, prev_end = ws[idx - 1]
            gap = code[prev_end:start]
            in_import = (prev == "import" and bool(gap) and all(ch in " \t" for ch in gap)) or (
                in_import and gap == "."
            )
        else:
            in_import = False
        if in_import and word in IMPORTABLE:
            continue
        if word.startswith("#eval"):
            return "#eval"
        if word == "eval" and code[end:].startswith("%"):
            return "eval%"
        if word in EXEC_WORDS:
            return word
    return None


def exec_token(source: str) -> str | None:
    """Why ``source`` may not be elaborated at all, or ``None``.

    A construct :func:`lean_code` cannot read unambiguously, or a word that runs code
    at elaboration time. Comments and string contents do not count. Every entry point
    that sends text to Lean applies this first.
    """
    try:
        code = lean_code(source)
    except LeanSourceError as exc:
        return str(exc)
    return exec_word(code)


def forbidden_token(source: str, *, allow_sorry: bool = False) -> str | None:
    """The first forbidden token in ``source``, or ``None``.

    ``sorry`` (unless ``allow_sorry``, used only for a frozen statement whose proof is
    the placeholder), ``native_decide``, a user ``axiom`` declaration (after any
    modifier or attribute), ``set_option pp.*``/``debug.*``, and everything
    :func:`exec_token` refuses. Comments and string contents do not count. A plain
    substring test is used for ``sorry`` and ``native_decide`` on purpose: an
    identifier merely containing them is refused too — fail closed.
    """
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return f"source larger than {MAX_SOURCE_BYTES} bytes"
    try:
        code = lean_code(source)
    except LeanSourceError as exc:
        return str(exc)
    if not allow_sorry and "sorry" in code:
        return "sorry"
    if "native_decide" in code:
        return "native_decide"
    ws = [w for w, _ in words(code)]
    if "axiom" in ws:
        return "axiom"
    for first, second in zip(ws, ws[1:], strict=False):
        if first == "set_option" and second in BANNED_OPTION_ROOTS:
            return f"set_option {second}"
    return exec_word(code)


# --- declarations ------------------------------------------------------------------

_DECL_RE = re.compile(
    r"(?m)(?:^|(?<=[\s\]]))(theorem|lemma)\s+([^\s:({\[⦃]+)",
)
_SCOPE_RE = re.compile(r"(?m)^[ \t]*(namespace|section|end)\b[ \t]*([^\s]*)")


def theorem_names(source: str) -> list[str]:
    """Fully qualified names of the ``theorem``/``lemma`` declarations, in order.

    ``namespace``/``section``/``end`` are tracked so ``theorem t`` inside
    ``namespace Foo`` is audited as ``Foo.t``. Unnamed ``example`` declarations are
    not listed: they cannot be named in ``#print axioms``. A name this misreads makes
    the appended ``#print axioms`` fail, which rejects — never accepts.
    """
    try:
        code = lean_code(source)
    except LeanSourceError:
        return []
    events: list[tuple[int, str, str]] = []
    for m in _SCOPE_RE.finditer(code):
        events.append((m.start(), m.group(1), m.group(2)))
    for m in _DECL_RE.finditer(code):
        events.append((m.start(), "decl", m.group(2)))
    events.sort(key=lambda e: e[0])
    stack: list[str] = []
    names: list[str] = []
    for _pos, kind, arg in events:
        if kind == "namespace":
            stack.append(arg)
        elif kind == "section":
            stack.append("")
        elif kind == "end":
            if stack:
                stack.pop()
        else:
            name = arg
            if name.startswith("_root_."):
                qualified = name[len("_root_.") :]
            else:
                prefix = ".".join(p for p in stack if p)
                qualified = f"{prefix}.{name}" if prefix else name
            if qualified not in names:
                names.append(qualified)
    return names


# --- the appended report ----------------------------------------------------------


def fresh_marker() -> str:
    """A per-run marker the candidate cannot predict (OS randomness)."""
    return "opentorus-report-" + secrets.token_hex(16)


def check_line(thm: str) -> str:
    """The ``pp.all`` type probe, placed last so its output runs to the end."""
    return f"set_option pp.all true in\n#check @{thm}\n"


def report_commands(marker: str, thms: list[str], *, type_of: str | None = None) -> str:
    """What the gate appends after the whole file: marker, axioms, optional type probe."""
    lines = [f'\n#print "{marker}"']
    lines += [f"#print axioms {t}" for t in thms]
    text = "\n".join(lines) + "\n"
    if type_of is not None:
        text += check_line(type_of)
    return text


# Lean prints info messages either bare or with a ``file:line:col: info:`` header,
# depending on the version; accept both, nothing else.
_MSG_PREFIX = re.compile(r"^(?:info:\s+)?(?:\S*?:\d+:\d+:\s+)?(?:info:\s+)?")


def _clean(line: str) -> str:
    return _MSG_PREFIX.sub("", line, count=1).rstrip()


class Report:
    """What the gate's own appended commands printed."""

    def __init__(self, axioms: dict[str, list[str]], type_text: str | None) -> None:
        self.axioms = axioms
        self.type_text = type_text


def parse_report(
    output: str, marker: str, thms: list[str], *, type_of: str | None = None
) -> Report | None:
    """Read only what follows the one line that is exactly ``marker``.

    It must be one axioms block per name in ``thms`` (in order), then — when
    ``type_of`` is given — the ``#check`` block, and nothing else. ``None`` when the
    marker is missing or repeated or the report has any other shape: output the
    candidate controls (its own commands run first) is never read.
    """
    if output.count(marker) != 1:
        return None
    lines = output.splitlines()
    idx = next((i for i, ln in enumerate(lines) if _clean(ln).strip() == marker), None)
    if idx is None:
        return None
    rest = lines[idx + 1 :]
    pos = 0
    axioms: dict[str, list[str]] = {}
    for thm in thms:
        while pos < len(rest) and not rest[pos].strip():
            pos += 1
        if pos >= len(rest):
            return None
        head = _clean(rest[pos])
        pos += 1
        quoted = f"'{thm}' "
        if not head.startswith(quoted):
            return None
        tail = head[len(quoted) :]
        if tail == "does not depend on any axioms":
            axioms[thm] = []
            continue
        if not tail.startswith("depends on axioms: ["):
            return None
        body = tail[len("depends on axioms: [") :]
        # Lean wraps a long axiom list across lines.
        while "]" not in body:
            if pos >= len(rest):
                return None
            body += " " + rest[pos].strip()
            pos += 1
        inner, _, after = body.partition("]")
        if after.strip() or "[" in inner:
            return None
        axioms[thm] = [a.strip() for a in inner.split(",") if a.strip()]
    remaining = "\n".join(rest[pos:]).strip()
    if type_of is None:
        return Report(axioms, None) if not remaining else None
    if not remaining:
        return None
    first, _, others = remaining.partition("\n")
    remaining = (_clean(first) + ("\n" + others if others else "")).strip()
    if not _starts_with_type_head(remaining, type_of):
        return None
    return Report(axioms, remaining)


def _starts_with_type_head(text: str, thm: str) -> bool:
    rest = text[1:] if text.startswith("@") else text
    if not rest.startswith(thm):
        return False
    rest = rest[len(thm) :]
    if rest.startswith(".{"):
        names, sep, after = rest[2:].partition("}")
        if not sep or not all(ch.isalnum() or ch in "_," or ch.isspace() for ch in names):
            return False
        rest = after
    return rest.lstrip(" \n").startswith(":")


def normalize_type(text: str) -> str:
    """Whitespace-insensitive form of a printed type (line wrapping is cosmetic)."""
    return " ".join(text.split())


def untrusted_axioms(axioms: list[str]) -> list[str]:
    return [a for a in axioms if a not in TRUSTED_AXIOMS]


# --- frozen statements ------------------------------------------------------------


def _norm(text: str) -> str:
    return " ".join(text.split())


def statement_span(frozen: str) -> tuple[int, int] | None:
    """The frozen statement: from the first line of code that starts with
    ``theorem``/``lemma`` (after optional modifiers/attributes) to the last ``:=``
    of code, inclusive. Found on :func:`lean_code`, so a comment cannot move it."""
    try:
        code = lean_code(frozen)
    except LeanSourceError:
        return None
    m = re.search(
        r"(?m)^[ \t]*(?:@\[[^\]\n]*\][ \t]*)?(?:(?:private|protected|nonrec)[ \t]+)*"
        r"(?:theorem|lemma)\b",
        code,
    )
    if m is None:
        return None
    start = m.start() + (len(m.group(0)) - len(m.group(0).lstrip()))
    end = code.rfind(":=")
    if end < start:
        return None
    return start, end + 2


def extract_statement(frozen: str) -> str | None:
    span = statement_span(frozen)
    return frozen[span[0] : span[1]] if span else None


def frozen_objection(frozen: str) -> str | None:
    """Why ``frozen`` cannot be registered as a frozen Lean statement, or ``None``.

    Read by :func:`lean_code`; no token :func:`forbidden_token` refuses apart from
    the placeholder ``sorry``; a statement is extractable and names one theorem; the
    proof after its ``:=`` is ``sorry`` or ``by sorry`` alone; ``sorry`` appears
    nowhere before it; and the preamble does not end in ``in`` (whose scope would be
    the separator command, not the theorem).
    """
    bad = forbidden_token(frozen, allow_sorry=True)
    if bad:
        return f"forbidden token {bad!r}"
    span = statement_span(frozen)
    if span is None:
        return "no `theorem`/`lemma … :=` statement found"
    code = lean_code(frozen)
    if _norm(code[span[1] :]) not in ("sorry", "by sorry"):
        return "the proof after the statement's `:=` must be `sorry` or `by sorry` alone"
    if "sorry" in code[: span[1]]:
        return "`sorry` appears before the statement's proof"
    names = theorem_names(frozen)
    if len(names) != 1:
        return f"a frozen file must declare exactly one theorem (found {len(names)})"
    pre_words = [w for w, _ in words(code[: span[0]])]
    if pre_words and pre_words[-1] == "in":
        return "the preamble's last command ends in `in`"
    return None


def preamble(frozen: str) -> str:
    """The frozen file up to its last character of code before the statement."""
    span = statement_span(frozen)
    if span is None:
        return ""
    code = lean_code(frozen)
    end = len(code[: span[0]].rstrip())
    return frozen[:end]


def checked_source(frozen: str, candidate: str) -> tuple[str, str]:
    """``(file Lean checks, candidate text after its preamble copy)``.

    The frozen preamble through its last character of code, :data:`SEPARATOR` on
    that line, then the candidate from the end of *its* copy of the preamble on.
    Line numbers are padded to the candidate's own. Raises :class:`LeanSourceError`
    when the candidate does not keep the preamble (whitespace-insensitively).
    """
    pre = preamble(frozen)
    if not pre.strip():
        return candidate, candidate
    pre_code = lean_code(pre)
    cand_code = lean_code(candidate)
    want = [ch for ch in pre_code if not ch.isspace()]
    j = 0
    cand_end = 0
    for i, ch in enumerate(cand_code):
        if j == len(want):
            break
        if ch.isspace():
            continue
        if ch != want[j]:
            raise LeanSourceError("the candidate does not begin with the frozen preamble")
        j += 1
        cand_end = i + 1
    if j < len(want):
        raise LeanSourceError("the candidate does not begin with the frozen preamble")
    rest = candidate[cand_end:]
    padding = max(0, candidate[:cand_end].count("\n") - pre.count("\n"))
    return f"{pre} {SEPARATOR}" + "\n" * padding + rest, rest


def contains_statement(candidate: str, statement: str) -> bool:
    """Whether ``candidate``'s code contains ``statement`` (whitespace-normalized).

    Both sides are read as code, so a statement copied into a comment does not count.
    """
    try:
        return _norm(lean_code(statement)) in _norm(lean_code(candidate))
    except LeanSourceError:
        return False


__all__ = [
    "BANNED_OPTION_ROOTS",
    "EXEC_WORDS",
    "LeanSourceError",
    "Report",
    "SEPARATOR",
    "TRUSTED_AXIOMS",
    "checked_source",
    "contains_statement",
    "exec_token",
    "extract_statement",
    "forbidden_token",
    "fresh_marker",
    "frozen_objection",
    "lean_code",
    "normalize_type",
    "parse_report",
    "preamble",
    "report_commands",
    "theorem_names",
    "untrusted_axioms",
]
