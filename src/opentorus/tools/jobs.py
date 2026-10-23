"""Background shell jobs: long work that stays visible and stoppable.

``run_shell(background=true)`` starts the command as a job and returns its id at
once; ``shell_jobs`` lists the session's jobs, reads the tail of their output and
stops them. Each job is its own process group (killed whole on stop, on its
deadline, and when the session's process exits), runs with the same clean
environment as a foreground ``run_shell``, and writes stdout/stderr to files
under ``.opentorus/jobs/``.

When a job finishes, :func:`drain_notices` hands the agent loop a one-line notice
("JOB-2 finished, exit 0") which the loop records as a message, so the model never
needs to wait for a job in a loop or with ``sleep``.
"""

from __future__ import annotations

import atexit
import os
import shlex
import subprocess
import tempfile
import threading
import time
import uuid
import weakref
from dataclasses import dataclass, field
from pathlib import Path

from opentorus.tools.base import Tool, ToolCall, ToolResult

_TAIL_BYTES = 4000

JOB_RULES = (
    "Never wait for a job in a loop or with sleep; never detach a process (setsid, nohup) "
    "-- a background job keeps long work visible and stoppable. You are told when a job "
    "finishes; read its output with shell_jobs."
)


@dataclass
class Job:
    job_id: str
    command: str
    proc: subprocess.Popen
    out_path: Path
    err_path: Path
    started: float = field(default_factory=time.monotonic)
    deadline: float = 0.0
    exit_code: int | None = None
    finished: float | None = None
    stopped: bool = False
    timed_out: bool = False

    @property
    def state(self) -> str:
        if self.exit_code is None:
            return "running"
        if self.stopped:
            return "stopped"
        if self.timed_out:
            return "timed out"
        return "finished"


class JobManager:
    """The background jobs of one session (one registry)."""

    def __init__(self, jobs_dir: Path | None = None, *, max_jobs: int = 4) -> None:
        self._dir = jobs_dir
        self.max_jobs = max_jobs
        self._jobs: dict[str, Job] = {}
        self._notices: list[str] = []
        self._lock = threading.Lock()
        self._counter = 0
        _MANAGERS.add(self)

    def _job_dir(self) -> Path:
        if self._dir is None:
            self._dir = Path(tempfile.mkdtemp(prefix="opentorus-jobs-"))
        self._dir.mkdir(parents=True, exist_ok=True)
        return self._dir

    def running(self) -> list[Job]:
        return [j for j in self._jobs.values() if j.exit_code is None]

    def start(
        self,
        command: str,
        *,
        cwd: Path,
        timeout: float,
        env_allowlist: tuple[str, ...] = (),
    ) -> Job:
        from opentorus.tools.childenv import clean_env

        if len(self.running()) >= self.max_jobs:
            raise RuntimeError(
                f"{self.max_jobs} background jobs are already running; stop one with "
                "shell_jobs(action='stop') or wait for the finish notice."
            )
        argv = command if os.name == "nt" else shlex.split(command)
        if not argv:
            raise ValueError("empty command")
        with self._lock:
            self._counter += 1
            job_id = f"JOB-{self._counter}"
        base = self._job_dir() / f"{job_id}-{uuid.uuid4().hex[:6]}"
        out_path, err_path = base.with_suffix(".out"), base.with_suffix(".err")
        with open(out_path, "wb") as out, open(err_path, "wb") as err:
            proc = subprocess.Popen(
                argv,
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                env=clean_env(allowlist=env_allowlist),
                start_new_session=os.name != "nt",
            )
        job = Job(
            job_id=job_id,
            command=command,
            proc=proc,
            out_path=out_path,
            err_path=err_path,
            deadline=time.monotonic() + timeout,
        )
        self._jobs[job_id] = job
        threading.Thread(target=self._watch, args=(job,), daemon=True).start()
        return job

    def _watch(self, job: Job) -> None:
        from opentorus.tools.shell import terminate_process_group

        while True:
            remaining = job.deadline - time.monotonic()
            try:
                job.proc.wait(timeout=max(0.05, min(remaining, 1.0)))
                break
            except subprocess.TimeoutExpired:
                if job.stopped:
                    break
                if time.monotonic() >= job.deadline:
                    job.timed_out = True
                    break
        # Whatever ended it, the whole group goes (leftover grandchildren included).
        try:
            terminate_process_group(job.proc, grace=2.0 if job.timed_out else 0.5)
        except OSError:
            pass
        job.exit_code = job.proc.returncode if job.proc.returncode is not None else -1
        job.finished = time.monotonic()
        with self._lock:
            self._notices.append(self.describe(job))

    def describe(self, job: Job) -> str:
        took = (job.finished or time.monotonic()) - job.started
        if job.state == "running":
            return f"{job.job_id} running for {took:.0f}s: {job.command}"
        return (
            f"Background job {job.job_id} {job.state} after {took:.0f}s "
            f"(exit {job.exit_code}): {job.command}. "
            f"Read its output with shell_jobs(action='read', job_id='{job.job_id}')."
        )

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def jobs(self) -> list[Job]:
        return list(self._jobs.values())

    def tail(self, job_id: str, max_bytes: int = _TAIL_BYTES) -> tuple[str, str]:
        job = self._jobs[job_id]

        def _tail(path: Path) -> str:
            try:
                with open(path, "rb") as fh:
                    fh.seek(0, os.SEEK_END)
                    size = fh.tell()
                    fh.seek(max(0, size - max_bytes))
                    data = fh.read()
            except OSError:
                return ""
            text = data.decode("utf-8", errors="replace")
            return (f"…({size - max_bytes} earlier bytes)\n" + text) if size > max_bytes else text

        return _tail(job.out_path), _tail(job.err_path)

    def stop(self, job_id: str) -> Job:
        job = self._jobs[job_id]
        if job.exit_code is None:
            job.stopped = True
            from opentorus.tools.shell import terminate_process_group

            try:
                terminate_process_group(job.proc, grace=2.0)
            except OSError:
                pass
            deadline = time.monotonic() + 5
            while job.exit_code is None and time.monotonic() < deadline:
                time.sleep(0.02)
        return job

    def drain(self) -> list[str]:
        with self._lock:
            notices, self._notices = self._notices, []
        return notices

    def close(self) -> None:
        """Kill every running job (session end)."""
        for job in self.running():
            try:
                self.stop(job.job_id)
            except Exception:  # noqa: BLE001 — cleanup must not raise
                pass


_MANAGERS: weakref.WeakSet[JobManager] = weakref.WeakSet()


def close_all_jobs() -> None:
    for manager in list(_MANAGERS):
        manager.close()


atexit.register(close_all_jobs)


def drain_notices(registry) -> list[str]:  # noqa: ANN001
    """Finish notices for the registry's background jobs (the agent loop's hook)."""
    tool = registry.get("shell_jobs") if registry is not None else None
    manager = getattr(tool, "manager", None)
    return manager.drain() if isinstance(manager, JobManager) else []


class ShellJobsTool(Tool):
    name = "shell_jobs"
    description = (
        "List this session's background jobs (started with run_shell background=true), "
        "read the tail of a job's output, or stop a job. " + JOB_RULES
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "read", "stop"]},
            "job_id": {"type": "string", "description": "e.g. JOB-1 (for read/stop)."},
        },
        "required": ["action"],
    }
    risk_level = "low"
    effect = "compensatable"

    def __init__(self, manager: JobManager) -> None:
        self.manager = manager

    def run(self, call: ToolCall) -> ToolResult:
        action = call.args.get("action")
        if action == "list":
            jobs = self.manager.jobs()
            if not jobs:
                return self.ok(call, "No background jobs in this session.")
            lines = [
                f"{j.job_id}  {j.state}"
                + (f" (exit {j.exit_code})" if j.exit_code is not None else "")
                + f"  {j.command}"
                for j in jobs
            ]
            return self.ok(call, "\n".join(lines))
        job_id = str(call.args.get("job_id") or "")
        if self.manager.get(job_id) is None:
            known = ", ".join(j.job_id for j in self.manager.jobs()) or "none"
            return self.fail(call, f"No job '{job_id}' in this session (jobs: {known}).")
        if action == "read":
            out, err = self.manager.tail(job_id)
            job = self.manager.get(job_id)
            assert job is not None
            body = f"{job.job_id} {job.state}"
            if job.exit_code is not None:
                body += f" exit_code={job.exit_code}"
            if out.strip():
                body += f"\nstdout (tail):\n{out.rstrip()}"
            if err.strip():
                body += f"\nstderr (tail):\n{err.rstrip()}"
            return self.ok(call, body, state=job.state)
        if action == "stop":
            job = self.manager.stop(job_id)
            return self.ok(call, f"{job.job_id} {job.state} (exit {job.exit_code}).")
        return self.fail(call, "action must be one of: list, read, stop.")
