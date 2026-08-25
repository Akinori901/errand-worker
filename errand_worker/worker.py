"""The worker: poll a queue, run Claude Code (subscription), write the result.

This is the generic core. It does not know about any particular application —
a job carries a prompt (and optionally a codebase ``cwd``), the worker runs the
local ``claude`` CLI headlessly, and writes the output to the sink.

AI is invoked via the locally-installed ``claude`` CLI (Claude Code). No API key
is used or required; the CLI runs under your logged-in subscription.

⚠️  Intended for an individual running jobs for themselves on their own Claude
    Code environment. Using a Claude subscription as the generation engine of a
    SaaS served to third parties may violate Anthropic's terms — check them.
"""
from __future__ import annotations

import subprocess
import sys
import time
from typing import Callable

from .config import Config
from .sink import Sink
from .store import Job, JobStore

# A pre-processing hook: transform the prompt before it reaches Claude
# (e.g. redaction/masking). Default is identity. Return the text to send.
PreProcess = Callable[[Job, str], str]


def _identity(_job: Job, prompt: str) -> str:
    return prompt


def run_claude(cfg: Config, job: Job) -> str:
    """Invoke ``claude -p`` headlessly and return stdout.

    If the job has a ``cwd`` (a codebase), Claude is allowed to read it with
    Read/Glob/Grep so it can ground its answer in real code. Write/execute
    tools are always disallowed so headless runs never stall on approval.
    """
    model = job.model or cfg.default_model
    cwd = job.cwd or (str(cfg.claude_cwd) if cfg.claude_cwd else None)

    args = [cfg.claude_bin, "-p", job.prompt, "--model", model]
    if cwd:
        # Ground the answer in the codebase, read-only, bounded.
        args += ["--allowedTools", "Read,Glob,Grep", "--max-turns", "25"]
    else:
        args += ["--disallowedTools", "Write,Edit,NotebookEdit,Bash"]

    proc = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=cfg.claude_timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI failed (rc={proc.returncode}): {proc.stderr[:500]}")
    out = proc.stdout.strip()
    if not out:
        raise RuntimeError("claude returned no output")
    return proc.stdout


def process(cfg: Config, store: JobStore, sink: Sink, job: Job, pre: PreProcess) -> None:
    print(f"[job {job.id}] owner={job.owner} cwd={job.cwd or '-'} -> running")
    prompt = pre(job, job.prompt)
    job.prompt = prompt
    result = run_claude(cfg, job)
    ref = sink.put(job.owner, job.id, result)
    store.complete(job, ref)
    print(f"[job {job.id}] done -> {ref}")


def poll_once(cfg: Config, store: JobStore, sink: Sink, pre: PreProcess) -> bool:
    """Claim and process one job. Returns True if a job was handled."""
    job = store.claim_next(cfg.owner)
    if job is None:
        return False
    try:
        process(cfg, store, sink, job, pre)
    except Exception as e:  # noqa: BLE001 — worker must survive any single job
        store.fail(job, f"{type(e).__name__}: {e}")
        print(f"[job {job.id}] error: {e}", file=sys.stderr)
    return True


def run_forever(cfg: Config, store: JobStore, sink: Sink, pre: PreProcess = _identity) -> None:
    """Poll loop. Survives transient errors; sleeps ``poll_interval`` when idle."""
    print(f"[errand-worker] polling as owner={cfg.owner} every {cfg.poll_interval}s")
    while True:
        try:
            worked = poll_once(cfg, store, sink, pre)
        except Exception as e:  # noqa: BLE001 — keep the loop alive
            print(f"[errand-worker] unexpected error, continuing: {e}", file=sys.stderr)
            worked = False
        if not worked:
            time.sleep(cfg.poll_interval)
