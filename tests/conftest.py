from __future__ import annotations

from pathlib import Path

import pytest

from errand_worker.config import Config


@pytest.fixture
def make_config(tmp_path: Path):
    """Build a Config without reading the environment or a .env file."""

    def _make(**overrides) -> Config:
        values = {
            "owner": "default",
            "store": "local",
            "jobs_table": "errand-jobs",
            "local_store_dir": tmp_path / "jobs",
            "sink": "local",
            "s3_bucket": "",
            "results_dir": tmp_path / "results",
            "aws_region": "us-east-1",
            "aws_profile": None,
            "poll_interval": 0.0,
            "claude_bin": "claude",
            "default_model": "sonnet",
            "claude_cwd": None,
            "claude_timeout": 10.0,
            "allowed_roots": [],
            "stale_after": 600.0,
            "max_attempts": 3,
        }
        values.update(overrides)
        return Config(**values)

    return _make
