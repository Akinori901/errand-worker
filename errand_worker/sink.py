"""Result sink abstraction.

The worker writes a job's result somewhere and records a reference (``result_ref``)
back on the job. Local directory by default (no cloud); S3 adapter for production.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Sink(Protocol):
    def put(self, owner: str, job_id: str, content: str) -> str: ...


class LocalSink:
    """Write each result to ``<base_dir>/<owner>/<job_id>.txt``. Returns the path."""

    def __init__(self, base_dir: Path):
        self.dir = Path(base_dir)

    def put(self, owner: str, job_id: str, content: str) -> str:
        out_dir = self.dir / owner
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{job_id}.txt"
        path.write_text(content, encoding="utf-8")
        return str(path)


class S3Sink:
    """Write each result to ``s3://<bucket>/<owner>/<job_id>.txt``. Returns the key."""

    def __init__(self, bucket: str, region: str, profile: str | None = None):
        import boto3

        session = boto3.Session(profile_name=profile) if profile else boto3.Session()
        self.s3 = session.client("s3", region_name=region)
        self.bucket = bucket

    def put(self, owner: str, job_id: str, content: str) -> str:
        key = f"{owner}/{job_id}.txt"
        self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
        )
        return f"s3://{self.bucket}/{key}"
