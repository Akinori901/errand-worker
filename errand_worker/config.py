"""Configuration, loaded from environment (and an optional .env file).

Everything defaults to a local, cloud-free setup so ``errand-worker`` runs
right after ``git clone``. Set ``ERRAND_STORE=dynamodb`` to switch to AWS.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE = Path.cwd()


def _load_dotenv() -> None:
    """Minimal .env loader (no dependency). Reads ./.env if present."""
    env_path = BASE / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def _allowed_roots(raw: str | None, default_cwd: str | None) -> list[Path]:
    if raw:
        return [Path(r).expanduser() for r in raw.split(os.pathsep) if r.strip()]
    return [Path(default_cwd)] if default_cwd else []


def _stale_after(raw: str | None, claude_timeout: float) -> float:
    """Default: the claude timeout plus 5 minutes. Never shorter than the timeout."""
    value = float(raw) if raw else claude_timeout + 300
    if value <= claude_timeout:
        raise ValueError(
            f"ERRAND_STALE_AFTER ({value}) must be longer than ERRAND_CLAUDE_TIMEOUT ({claude_timeout}),"
            " or jobs that are still running would be claimed twice"
        )
    return value


@dataclass
class Config:
    owner: str
    # job store: "local" (files, no AWS) | "dynamodb"
    store: str
    jobs_table: str
    local_store_dir: Path
    # result sink: "local" (dir) | "s3"
    sink: str
    s3_bucket: str
    results_dir: Path
    aws_region: str
    aws_profile: str | None
    # polling
    poll_interval: float
    # claude CLI
    claude_bin: str
    default_model: str
    # working dir for claude (a codebase root it may read); a job's own cwd overrides
    claude_cwd: Path | None
    # subprocess timeout for a single claude run (seconds)
    claude_timeout: float
    # directories a job's cwd must be inside (ERRAND_ALLOWED_ROOTS, os.pathsep-separated).
    # Jobs come from a web backend, so without this a job could point Claude at
    # "/" or "~/.aws". Defaults to ERRAND_CLAUDE_CWD alone; empty means jobs
    # cannot choose a cwd at all.
    allowed_roots: list[Path]
    # a "running" job not updated for this long is treated as abandoned (its worker
    # died) and claimed again. Must exceed claude_timeout so live jobs aren't stolen.
    stale_after: float
    # a job claimed this many times without finishing is marked as error instead of
    # retried forever (e.g. a job that crashes the worker every time)
    max_attempts: int

    @classmethod
    def load(cls) -> Config:
        _load_dotenv()
        e = os.environ.get
        cwd = e("ERRAND_CLAUDE_CWD")
        return cls(
            owner=e("ERRAND_OWNER", "default"),
            store=e("ERRAND_STORE", "local"),
            jobs_table=e("ERRAND_JOBS_TABLE", "errand-jobs"),
            local_store_dir=Path(e("ERRAND_LOCAL_STORE", str(BASE / ".errand" / "jobs"))),
            sink=e("ERRAND_SINK", "local"),
            s3_bucket=e("ERRAND_S3_BUCKET", ""),
            results_dir=Path(e("ERRAND_RESULTS_DIR", str(BASE / ".errand" / "results"))),
            aws_region=e("AWS_REGION", "us-east-1"),
            aws_profile=e("AWS_PROFILE") or None,
            poll_interval=float(e("ERRAND_POLL_INTERVAL", "5")),
            claude_bin=e("ERRAND_CLAUDE_BIN", "claude"),
            default_model=e("ERRAND_DEFAULT_MODEL", "sonnet"),
            claude_cwd=Path(cwd) if cwd else None,
            claude_timeout=float(e("ERRAND_CLAUDE_TIMEOUT", "900")),
            allowed_roots=_allowed_roots(e("ERRAND_ALLOWED_ROOTS"), cwd),
            stale_after=_stale_after(e("ERRAND_STALE_AFTER"), float(e("ERRAND_CLAUDE_TIMEOUT", "900"))),
            max_attempts=int(e("ERRAND_MAX_ATTEMPTS", "3")),
        )
