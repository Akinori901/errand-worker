"""Job store abstraction.

Contract:
  status: queued -> running -> done | error
  claim_next(): take one queued job and atomically win "running" (dedup-safe)

A job is deliberately generic: it carries a ``prompt`` (what to ask Claude),
an optional ``cwd`` (a codebase to let Claude read), and a ``model``. The
worker is not tied to any particular application; callers enqueue jobs and
read results by ``result_ref``.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class Job:
    """A unit of work for the worker.

    id:         unique job id (caller-supplied; ULID/UUID recommended)
    owner:      partition key — lets one queue serve multiple users/apps
    status:     queued -> running -> done | error
    prompt:     the instruction passed to Claude (``claude -p <prompt>``)
    cwd:        optional path to a codebase Claude may read (Read/Glob/Grep)
    model:      optional model alias (e.g. "opus", "sonnet")
    result_ref: filled on completion — where the result was written (sink key)
    error:      filled on failure
    updated_at: ISO8601, maintained by the store
    """

    id: str
    owner: str = "default"
    status: str = "queued"
    prompt: str = ""
    cwd: str | None = None
    model: str | None = None
    result_ref: str = ""
    error: str = ""
    updated_at: str = ""

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> "Job":
        known = {f: item.get(f) for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in known.items() if v is not None})


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class JobStore(Protocol):
    def claim_next(self, owner: str) -> Job | None: ...
    def complete(self, job: Job, result_ref: str) -> None: ...
    def fail(self, job: Job, error: str) -> None: ...


class LocalJobStore:
    """One file = one job (JSON). No cloud required — clone and run.

    Enqueueing (normally done by your web backend) is available here via
    ``enqueue()`` so the whole loop can be exercised locally.
    """

    def __init__(self, base_dir: Path):
        self.dir = Path(base_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job: Job) -> Path:
        return self.dir / f"{job.owner}__{job.id}.json"

    def enqueue(self, job: Job) -> Job:
        job.status = "queued"
        job.updated_at = _now()
        self._save(job)
        return job

    def _save(self, job: Job) -> None:
        job.updated_at = _now()
        self._path(job).write_text(
            json.dumps(asdict(job), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def claim_next(self, owner: str) -> Job | None:
        for p in sorted(self.dir.glob(f"{owner}__*.json")):
            item = json.loads(p.read_text(encoding="utf-8"))
            if item.get("status") == "queued":
                job = Job.from_item(item)
                job.status = "running"
                self._save(job)  # single-process locally: optimistic is enough
                return job
        return None

    def complete(self, job: Job, result_ref: str) -> None:
        job.status = "done"
        job.result_ref = result_ref
        self._save(job)

    def fail(self, job: Job, error: str) -> None:
        job.status = "error"
        job.error = error[:1000]
        self._save(job)


class DynamoJobStore:
    """Production store. Conditional update wins "running" (multi-worker safe).

    Table key schema: partition key ``owner`` (S), sort key ``id`` (S).
    boto3 is imported lazily so local usage needs no AWS dependency.
    """

    def __init__(self, table_name: str, region: str, profile: str | None = None):
        import boto3

        session = boto3.Session(profile_name=profile) if profile else boto3.Session()
        self.ddb = session.resource("dynamodb", region_name=region)
        self.table = self.ddb.Table(table_name)

    def claim_next(self, owner: str) -> Job | None:
        from boto3.dynamodb.conditions import Attr, Key
        from botocore.exceptions import ClientError

        # DynamoDB's Limit caps items READ (before filtering). With Limit=N +
        # FilterExpression(status=queued), the query reads only the first N items
        # of the partition (ascending sort-key = oldest first) and then filters.
        # Once N done jobs accumulate at the front, the newer queued jobs at the
        # tail are never reached -> "jobs are enqueued but never processed".
        # So we drop Limit and page with LastEvaluatedKey until a queued job is found.
        last_key: dict | None = None
        while True:
            kwargs: dict = {
                "KeyConditionExpression": Key("owner").eq(owner),
                "FilterExpression": Attr("status").eq("queued"),
            }
            if last_key:
                kwargs["ExclusiveStartKey"] = last_key
            resp = self.table.query(**kwargs)
            for item in resp.get("Items", []):
                try:
                    self.table.update_item(
                        Key={"owner": item["owner"], "id": item["id"]},
                        UpdateExpression="SET #s = :run, #u = :t",
                        ConditionExpression=Attr("status").eq("queued"),
                        ExpressionAttributeNames={"#s": "status", "#u": "updated_at"},
                        ExpressionAttributeValues={":run": "running", ":t": _now()},
                    )
                    item["status"] = "running"
                    return Job.from_item(item)
                except ClientError as e:
                    if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                        continue  # another worker won it
                    raise
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                return None

    def _update(self, job: Job, status: str, **extra: str) -> None:
        # status is a DynamoDB reserved word — alias every attribute name.
        expr = "SET #s = :st, #u = :t"
        vals: dict[str, str] = {":st": status, ":t": _now()}
        names = {"#s": "status", "#u": "updated_at"}
        for i, (k, v) in enumerate(extra.items()):
            expr += f", #k{i} = :e{i}"
            names[f"#k{i}"] = k
            vals[f":e{i}"] = v
        self.table.update_item(
            Key={"owner": job.owner, "id": job.id},
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=vals,
        )

    def complete(self, job: Job, result_ref: str) -> None:
        self._update(job, "done", result_ref=result_ref)

    def fail(self, job: Job, error: str) -> None:
        self._update(job, "error", error=error[:1000])
