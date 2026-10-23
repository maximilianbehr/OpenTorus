"""A resident Lean REPL backend (leanprover-community/repl JSON protocol).

``lake env lean file.lean`` re-elaborates ``import Mathlib`` on every submission —
tens of seconds before the first line of the proof is read. The REPL keeps one
process alive with the header elaborated once (environment ``env``), and each
submission is a command in that environment.

Protocol (one JSON object per command, terminated by a blank line, on stdin; one
JSON reply terminated by a blank line on stdout)::

    {"cmd": "import Mathlib"}                      -> {"env": 0}
    {"cmd": "theorem t : 1 = 1 := rfl", "env": 0}  -> {"env": 1, "messages": [...]}

Each message is ``{"severity": "error"|"warning"|"info", "pos": {"line", "column"},
"data": "..."}``. Replies are rendered as ``proof.lean:L:C: severity: data`` lines so
the *same* gate as the file backend reads them (marker, ``#print axioms``, type
probe): the REPL changes only how Lean is run, never what is accepted.

Robustness: every request has a deadline; a request that outlives it kills the
process (inconclusive, like a timeout); a process that died is respawned once per
request, and a second death is reported as a crash (inconclusive). Imports in the
submission must be covered by the resident header — otherwise the submission runs
as a fresh, header-less command (slower, still correct). Off by default
(``tools.verifiers.lean_repl``).
"""

from __future__ import annotations

import atexit
import json
import os
import selectors
import shlex
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from opentorus.research.verifiers.backends import Lean4Backend
from opentorus.research.verifiers.sandbox import confine_command
from opentorus.tools.shell import ShellResult

_HEADER_TIMEOUT_FLOOR = 600


class _ReplDied(RuntimeError):
    pass


class _ReplTimeout(RuntimeError):
    pass


class _ReplProcess:
    """One resident REPL process with its header environment."""

    def __init__(self, command: str, header: str, confine: str, cwd: str | None) -> None:
        self.command = command
        self.header = header
        self.confine = confine
        self.cwd = cwd
        self.proc: subprocess.Popen[bytes] | None = None
        self.env: int | None = None
        self.confined = False
        self.starts = 0
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self._buffer = b""
        self.lock = threading.Lock()

    # -- lifecycle ------------------------------------------------------------------

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def kill(self) -> None:
        if self.proc is not None:
            try:
                self.proc.kill()
                self.proc.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass
        self.proc = None
        self.env = None
        self._buffer = b""
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None

    def start(self, header_timeout: float) -> None:
        self.kill()
        self._tmp = tempfile.TemporaryDirectory(prefix="opentorus-repl-")
        command, self.confined = confine_command(
            self.command,
            writable=[Path(self._tmp.name)],
            mode=self.confine,  # type: ignore[arg-type]
        )
        self.proc = subprocess.Popen(
            shlex.split(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=self.cwd,
            # The only writable place inside the sandbox.
            env={**os.environ, "TMPDIR": self._tmp.name},
        )
        self.starts += 1
        if self.header.strip():
            reply = self.request({"cmd": self.header}, header_timeout)
            errors = [m for m in reply.get("messages", []) if m.get("severity") == "error"]
            if errors or "env" not in reply:
                self.kill()
                raise _ReplDied(f"the REPL header failed: {errors or reply}")
            self.env = int(reply["env"])

    # -- one request ----------------------------------------------------------------

    def request(self, payload: dict, timeout: float) -> dict:
        proc = self.proc
        if proc is None or proc.poll() is not None or proc.stdin is None or proc.stdout is None:
            raise _ReplDied("the REPL process is not running")
        try:
            proc.stdin.write((json.dumps(payload) + "\n\n").encode("utf-8"))
            proc.stdin.flush()
        except OSError as exc:
            raise _ReplDied(f"writing to the REPL failed: {exc}") from exc
        deadline = time.monotonic() + timeout
        fd = proc.stdout.fileno()
        with selectors.DefaultSelector() as sel:
            sel.register(fd, selectors.EVENT_READ)
            while True:
                reply = self._take_reply()
                if reply is not None:
                    return reply
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.kill()
                    raise _ReplTimeout(f"the REPL exceeded the {timeout:.0f}s deadline")
                if not sel.select(timeout=min(remaining, 1.0)):
                    if proc.poll() is not None:
                        raise _ReplDied(f"the REPL exited (code {proc.returncode})")
                    continue
                chunk = os.read(fd, 65536)
                if not chunk:
                    raise _ReplDied("the REPL closed its output")
                self._buffer += chunk

    def _take_reply(self) -> dict | None:
        """Pop one complete JSON reply (ends with a blank line) from the buffer.

        JSON strings escape newlines, so a blank line never occurs inside a reply.
        """
        while b"\n\n" in self._buffer:
            head, _, rest = self._buffer.partition(b"\n\n")
            self._buffer = rest
            text = head.decode("utf-8", "replace").strip()
            if not text:
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                self.kill()
                raise _ReplDied(f"unparseable REPL output: {text[:200]!r}") from exc
            return value if isinstance(value, dict) else {"message": f"unexpected {value!r}"}
        return None


_POOL: dict[tuple[str, str, str, str | None], _ReplProcess] = {}
_POOL_LOCK = threading.Lock()


def _shared_process(command: str, header: str, confine: str, cwd: str | None) -> _ReplProcess:
    key = (command, header, confine, cwd)
    with _POOL_LOCK:
        proc = _POOL.get(key)
        if proc is None:
            proc = _ReplProcess(command, header, confine, cwd)
            _POOL[key] = proc
        return proc


@atexit.register
def shutdown_all() -> None:
    """Kill every resident REPL (also used by tests)."""
    with _POOL_LOCK:
        for proc in _POOL.values():
            proc.kill()
        _POOL.clear()


def _header_imports(header: str) -> set[str]:
    return {
        line.split(None, 1)[1].strip()
        for line in header.splitlines()
        if line.strip().startswith("import ") and len(line.split(None, 1)) == 2
    }


def _split_imports(source: str) -> tuple[set[str], str]:
    """The submission's imports, and its body with import lines blanked (lines kept)."""
    imports: set[str] = set()
    lines = source.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("import "):
            imports.update(stripped.split()[1:])
            lines[i] = ""
        elif stripped and not stripped.startswith("--"):
            break
    return imports, "\n".join(lines)


def render_messages(messages: list[dict]) -> str:
    out = []
    for msg in messages:
        pos = msg.get("pos") or {}
        line = pos.get("line", 0)
        col = pos.get("column", 0)
        sev = msg.get("severity", "info")
        out.append(f"proof.lean:{line}:{col}: {sev}: {msg.get('data', '')}")
    return "\n".join(out)


class LeanReplBackend(Lean4Backend):
    """:class:`Lean4Backend` whose checker is a resident REPL process."""

    def __init__(
        self,
        command: str,
        timeout: int = 120,
        *,
        header: str = "import Mathlib",
        confine: str = "auto",
        cwd: str | None = None,
    ) -> None:
        super().__init__(command, timeout=timeout, confine=confine)
        self.header = header
        self.cwd = cwd

    def _process(self) -> _ReplProcess:
        return _shared_process(self.command, self.header, self.confine, self.cwd)

    def _run(self, source: str) -> tuple[ShellResult, bool]:
        """Send ``source`` to the resident REPL; same contract as the file backend."""
        repl = self._process()
        imports, body = _split_imports(source)
        covered = imports <= _header_imports(self.header)
        header_timeout = max(self.timeout, _HEADER_TIMEOUT_FLOOR)
        with repl.lock:
            for attempt in (0, 1):  # a single respawn per request
                try:
                    if not repl.alive():
                        repl.start(header_timeout)
                    payload: dict = (
                        {"cmd": body, "env": repl.env}
                        if covered and repl.env is not None
                        else {"cmd": source}
                    )
                    reply = repl.request(payload, float(self.timeout))
                    break
                except _ReplTimeout as exc:
                    return (
                        ShellResult(
                            command="lean-repl",
                            stdout="",
                            stderr=f"Timed out: {exc} (the REPL was killed; it respawns "
                            "on the next request).",
                            exit_code=124,
                            timed_out=True,
                        ),
                        repl.confined,
                    )
                except (_ReplDied, OSError) as exc:
                    repl.kill()
                    if attempt == 1:
                        return (
                            ShellResult(
                                command="lean-repl",
                                stdout="",
                                stderr=f"the Lean REPL died twice: {exc}",
                                exit_code=-9,
                            ),
                            repl.confined,
                        )
        messages = list(reply.get("messages") or [])
        stdout = render_messages(messages)
        failed = any(m.get("severity") == "error" for m in messages) or "message" in reply
        if "message" in reply:  # protocol-level error, e.g. unknown environment
            stdout += f"\nproof.lean:0:0: error: {reply['message']}"
        return (
            ShellResult(
                command="lean-repl", stdout=stdout, stderr="", exit_code=1 if failed else 0
            ),
            repl.confined,
        )


__all__ = ["LeanReplBackend", "render_messages", "shutdown_all"]
