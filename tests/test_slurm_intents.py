"""Intent-before-dispatch for Slurm (6g): an ssh timeout after sbatch is never resubmitted.

Runs against fake ``ssh``/``scp`` scripts -- never a real cluster.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from opentorus.execution.base import ExecutionRequest, RunLimits
from opentorus.execution.intents import IntentLog
from opentorus.execution.remote import SlurmBackend

pytestmark = pytest.mark.skipif(os.name == "nt", reason="fake POSIX executables")

_FAKE_SSH = """#!{python}
import json, os, re, sys, time
state = os.environ["FAKE_SLURM_STATE"]
jobs = json.load(open(state)) if os.path.exists(state) else {{}}
cmd = sys.argv[2]
mode = open(state + ".mode").read().strip() if os.path.exists(state + ".mode") else "ok"
if cmd.startswith("sbatch"):
    script = cmd.split()[-1].strip("'")
    name = re.search(r"--job-name=(\\S+)", open(script).read()).group(1)
    job_id = str(1000 + len(jobs))
    jobs[name] = job_id
    json.dump(jobs, open(state, "w"))
    if mode == "hang":
        time.sleep(30)  # the reply never arrives in time
    print(job_id)
elif cmd.startswith("squeue") or cmd.startswith("sacct"):
    if mode == "down":
        sys.exit(255)
    name = cmd.split("--name")[1].split()[0].strip("'")
    if cmd.startswith("squeue") and name in jobs:
        print(jobs[name])
else:
    sys.exit(2)
"""

_FAKE_SCP = """#!/bin/sh
# scp -r SRC HOST:DEST  -> copy SRC into DEST locally
src="$2"; dest="${3#*:}"
mkdir -p "$dest" && cp -r "$src" "$dest"
"""


def _exe(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def cluster(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    state = tmp_path / "jobs.json"
    monkeypatch.setenv("FAKE_SLURM_STATE", str(state))
    ssh = _exe(tmp_path / "fake-ssh", _FAKE_SSH.format(python=sys.executable))
    scp = _exe(tmp_path / "fake-scp", _FAKE_SCP)
    remote_root = tmp_path / "remote"
    backend = SlurmBackend(
        host="hpc", remote_root=str(remote_root), ssh_command=str(ssh), copy_command=str(scp)
    )
    workdir = tmp_path / "EXP-0001"
    (workdir / "results").mkdir(parents=True)
    request = ExecutionRequest(
        command="python run.py", workdir=workdir, limits=RunLimits(timeout=2)
    )

    def set_mode(mode: str) -> None:
        Path(str(state) + ".mode").write_text(mode, encoding="utf-8")

    def jobs() -> dict:
        return json.loads(state.read_text()) if state.exists() else {}

    return backend, request, set_mode, jobs


def test_normal_submission_records_intent_then_outcome(cluster) -> None:  # noqa: ANN001
    backend, request, set_mode, jobs = cluster
    set_mode("ok")
    result = backend.run(request)
    assert result.exit_code == 0 and result.stdout.strip() == "1000"
    records = backend.intent_log(request).records()
    assert [r["record"] for r in records] == ["intent", "outcome"]
    op_id = records[0]["op_id"]
    assert list(jobs()) == [op_id]  # the op id is the Slurm job name
    assert records[1]["outcome"] == "succeeded" and records[1]["job_id"] == "1000"


def test_timeout_after_sbatch_is_recovered_by_name_not_resubmitted(cluster) -> None:  # noqa: ANN001
    backend, request, set_mode, jobs = cluster
    set_mode("hang")
    result = backend.run(request)
    # The reply was lost, but squeue --name <op id> found the job.
    assert result.exit_code == 0 and result.stdout.strip() == "1000"
    assert "found job 1000" in result.stderr
    assert len(jobs()) == 1  # exactly one job, never two


def test_unknown_outcome_blocks_resubmission_until_resolved(cluster) -> None:  # noqa: ANN001
    backend, request, set_mode, jobs = cluster
    set_mode("hang")
    # The cluster cannot be queried either: the outcome is genuinely unknown.
    orig = backend.find_job
    backend.find_job = lambda op_id, timeout=60: (None, False)  # type: ignore[method-assign]
    first = backend.run(request)
    assert first.timed_out and "outcome unknown" in first.stderr
    log: IntentLog = backend.intent_log(request)
    (pending,) = log.unresolved()
    # A second run of the same request does not submit again while unresolved.
    second = backend.run(request)
    assert "unresolved" in second.stderr and second.exit_code == 124
    assert len(jobs()) == 1
    # Once the cluster answers, the earlier job is recovered by name.
    backend.find_job = orig  # type: ignore[method-assign]
    set_mode("ok")
    third = backend.run(request)
    assert third.exit_code == 0 and third.stdout.strip() == "1000"
    assert "not resubmitted" in third.stderr
    assert len(jobs()) == 1
    assert log.state(pending["op_id"]) == "succeeded"


def test_intent_is_on_disk_before_dispatch(cluster, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    backend, request, set_mode, _ = cluster
    seen: list[list[dict]] = []
    real = backend._runner  # noqa: SLF001

    def spy(argv, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if any("sbatch" in str(a) for a in argv):
            seen.append(backend.intent_log(request).records())
        return real(argv, *args, **kwargs)

    backend._runner = spy  # noqa: SLF001
    set_mode("ok")
    backend.run(request)
    assert seen and [r["record"] for r in seen[0]] == ["intent"]
