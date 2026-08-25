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

    @classmethod
    def load(cls) -> "Config":
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
        )
