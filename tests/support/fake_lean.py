"""A fake ``lean`` checker for gate tests (real Lean is not installed in CI).

``fake_lean_command(tmp_path)`` writes a small Python script and returns a command
string usable as ``tools.verifiers.lean_command``. The script imitates the parts of
``lean <file>`` the OpenTorus gate depends on:

* ``FAKE_ERROR`` anywhere → ``file:L:C: error: unknown identifier 'foo'``, exit 1;
  ``FAKE_UNSOLVED`` → an ``unsolved goals`` error with a goal; ``FAKE_TIMEOUT`` →
  sleeps (the caller's timeout fires);
* a ``theorem``/``lemma`` body containing ``sorry`` gets a
  ``declaration uses 'sorry'`` warning and depends on ``sorryAx``;
  ``FAKE_SORRYAX`` in a body depends on ``sorryAx`` *without* the warning (a proof
  hidden behind a macro); ``FAKE_EXTRA_AXIOM`` adds a non-standard axiom;
* ``#print "text"`` prints ``text``; ``#print axioms N`` prints Lean's axioms line
  (``error: unknown constant`` for an undeclared name); ``#check @N`` prints
  ``N : <signature>`` with the declaration's signature whitespace-normalized — a
  stand-in for the ``pp.all`` elaborated type (a different theorem prints a
  different type).

``FAKE_INFO_PREFIX=1`` in the environment prefixes info lines with
``file:L:C: info:`` like newer Lean versions do.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT = r"""
import os, re, sys, time
path = sys.argv[-1]
src = open(path, encoding="utf-8").read()
if os.environ.get("FAKE_LEAN_LOG"):
    with open(os.environ["FAKE_LEAN_LOG"], "a", encoding="utf-8") as fh:
        fh.write(src + "\n=====\n")
if "FAKE_TIMEOUT" in src:
    time.sleep(30)
prefix = os.environ.get("FAKE_INFO_PREFIX") == "1"
out = []
def info(line_no, text):
    out.append((f"{path}:{line_no}:0: info: " if prefix else "") + text)
decls = {}
lines = src.splitlines()
HEAD = r"\s*(?:@\[[^\]]*\]\s*)?(?:private\s+)?"
starts = [i for i, l in enumerate(lines) if re.match(HEAD + r"(theorem|lemma)\s", l)]
for n, i in enumerate(starts):
    end = starts[n + 1] if n + 1 < len(starts) else len(lines)
    chunk = "\n".join(lines[i:end])
    m = re.match(HEAD + r"(?:theorem|lemma)\s+(\S+)(.*?):=(.*)", chunk, re.S)
    if not m:
        continue
    name, sig, body = m.group(1), " ".join(m.group(2).split()), m.group(3)
    body = body.split("#print")[0]
    decls[name] = (i + 1, sig, body)
code = 0
for i, l in enumerate(lines, 1):
    if "FAKE_ERROR" in l:
        out.append(f"{path}:{i}:4: error: unknown identifier 'foo'")
        code = 1
    if "FAKE_UNSOLVED" in l:
        out.append(f"{path}:{i}:2: error: unsolved goals")
        out.append("n : Nat")
        out.append("⊢ n + 0 = n")
        code = 1
SUITE = {"rfl", "simp", "omega", "norm_num", "linarith", "nlinarith", "positivity",
         "decide", "aesop", "exact?"}
closes = None
for i, l in enumerate(lines, 1):
    s = l.strip()
    if re.match(r"(theorem|lemma)\s", s):
        closes = None
    m = re.match(r"-- closes: (\S+)$", s)
    if m:
        closes = m.group(1)
        continue
    if s == "by sorry" or s.endswith(" by sorry") and s.startswith("·"):
        out.append(f"{path}:{i}:2: error: unexpected token 'by'; expected tactic")
        code = 1
        continue
    tm = re.search(r"\(by ([^()]+)\)", s)
    tac = tm.group(1) if tm else s
    if tac in SUITE and closes is not None:
        if tm and closes.startswith("tactic-only"):
            out.append(f"{path}:{i}:2: error: type mismatch")
            code = 1
        elif tac != closes.replace("tactic-only:", ""):
            out.append(f"{path}:{i}:2: error: {tac} failed")
            code = 1
        elif tac == "exact?":
            out.append(f"{path}:{i}:2: info: Try this: exact Nat.add_zero n")
for name, (line_no, sig, body) in decls.items():
    if "sorry" in body:
        out.append(f"{path}:{line_no}:8: warning: declaration uses 'sorry'")
check_next = False
for i, l in enumerate(lines, 1):
    s = l.strip()
    m = re.match(r'#print "(.*)"$', s)
    if m:
        info(i, m.group(1))
        continue
    m = re.match(r"#print axioms (\S+)$", s)
    if m:
        name = m.group(1).split(".")[-1]
        if name not in decls:
            out.append(f"{path}:{i}:0: error: unknown constant '{m.group(1)}'")
            code = 1
            continue
        body = decls[name][2]
        axs = ["propext"]
        if "Classical" in body:
            axs = ["Classical.choice", "propext", "Quot.sound"]
        if "sorry" in body or "FAKE_SORRYAX" in body:
            axs.append("sorryAx")
        if "FAKE_EXTRA_AXIOM" in body:
            axs.append("myAxiom")
        if "FAKE_NO_AXIOMS" in body:
            info(i, f"'{m.group(1)}' does not depend on any axioms")
        else:
            info(i, f"'{m.group(1)}' depends on axioms: [{', '.join(sorted(axs))}]")
        continue
    m = re.match(r"#check @(\S+)$", s)
    if m:
        name = m.group(1).split(".")[-1]
        if name not in decls:
            out.append(f"{path}:{i}:0: error: unknown identifier '{m.group(1)}'")
            code = 1
            continue
        info(i, f"{m.group(1)} : {decls[name][1].lstrip(': ').strip()}")
print("\n".join(out))
sys.exit(code)
"""


def fake_lean_command(tmp_path: Path) -> str:
    """Write the fake checker under ``tmp_path`` and return its command string."""
    script = tmp_path / "fake_lean_bin.py"
    script.write_text(SCRIPT, encoding="utf-8")
    return f"{sys.executable} {script}"


COQ_SCRIPT = r"""
import re, sys
path = sys.argv[-1]
src = open(path, encoding="utf-8").read()
out = []
code = 0
decls = {}
DECL = r"(?:Theorem|Lemma)\s+(\w+)\s*(.*?)\.\s*(?:Proof\.)?(.*?)(?:Qed|Defined|Admitted)\."
for m in re.finditer(DECL, src, re.S):
    decls[m.group(1)] = (" ".join(m.group(2).split()), m.group(3))
if "FAKE_ERROR" in src:
    out.append(f'File "{path}", line 1, characters 0-5:')
    out.append("Error: The reference foo was not found in the current environment.")
    code = 1
for line in src.splitlines():
    s = line.strip()
    m = re.match(r"Locate (\w+)\.$", s)
    if m:
        out.append(f"No object of basename {m.group(1)}")
        continue
    m = re.match(r"Print Assumptions (\w+)\.$", s)
    if m:
        body = decls.get(m.group(1), ("", ""))[1]
        if "FAKE_AXIOM" in body or m.group(1) not in decls:
            out.append("Axioms:")
            out.append("classic : forall P : Prop, P \\/ ~ P")
        else:
            out.append("Closed under the global context")
        continue
    m = re.match(r"Check (\w+)\.$", s)
    if m and m.group(1) in decls:
        out.append(m.group(1))
        out.append("     " + decls[m.group(1)][0])
print("\n".join(out))
sys.exit(code)
"""


def fake_coq_command(tmp_path: Path) -> str:
    script = tmp_path / "fake_coqc_bin.py"
    script.write_text(COQ_SCRIPT, encoding="utf-8")
    return f"{sys.executable} {script}"


REPL_SCRIPT = r"""
import json, os, subprocess, sys, tempfile, time
FAKE_LEAN = sys.argv[1]
log = os.environ.get("FAKE_REPL_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("start\n")
envs = 0
buf = ""
def reply(obj):
    sys.stdout.write(json.dumps(obj, indent=2) + "\n\n")
    sys.stdout.flush()
def handle(req):
    global envs
    cmd = req.get("cmd", "")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write("cmd env=%s\n" % req.get("env"))
    if "FAKE_HANG" in cmd:
        time.sleep(60)
    if "FAKE_CRASH" in cmd:
        sys.exit(3)
    if cmd.strip().startswith("import") and "theorem" not in cmd:
        envs += 1
        return {"env": envs - 1}
    with tempfile.NamedTemporaryFile("w", suffix=".lean", delete=False) as fh:
        fh.write(cmd)
        path = fh.name
    env = dict(os.environ, FAKE_INFO_PREFIX="1")
    done = subprocess.run([sys.executable, FAKE_LEAN, path], capture_output=True, text=True,
                          env=env)
    os.unlink(path)
    messages = []
    for line in done.stdout.splitlines():
        parts = line.split(":", 4)
        if line.startswith(path) and len(parts) == 5:
            messages.append({"severity": parts[3].strip(),
                             "pos": {"line": int(parts[1]), "column": int(parts[2])},
                             "data": parts[4][1:]})
        elif messages:
            messages[-1]["data"] += "\n" + line
    envs += 1
    return {"env": envs - 1, "messages": messages}
for line in sys.stdin:
    if line.strip():
        buf += line
        continue
    if not buf.strip():
        continue
    req = json.loads(buf)
    buf = ""
    reply(handle(req))
"""


def fake_repl_command(tmp_path: Path) -> str:
    """A fake leanprover-community/repl speaking the JSON protocol over the fake lean."""
    lean = tmp_path / "fake_lean_bin.py"
    lean.write_text(SCRIPT, encoding="utf-8")
    script = tmp_path / "fake_repl_bin.py"
    script.write_text(REPL_SCRIPT, encoding="utf-8")
    return f"{sys.executable} {script} {lean}"
