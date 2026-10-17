from __future__ import annotations

from pathlib import Path

import pytest

from errand_worker.sink import LocalSink
from errand_worker.store import DynamoJobStore, Job, LocalJobStore, check_id


@pytest.mark.parametrize("value", ["default", "user@example.com", "a+b", "01HZX9K2", "job-1.v2"])
def test_check_id_accepts_safe_values(value: str) -> None:
    assert check_id("id", value) == value


@pytest.mark.parametrize("value", ["", "..", "../x", "a/b", ".hidden", "a\\b", "x" * 129])
def test_check_id_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError):
        check_id("id", value)


def test_local_sink_cannot_write_outside_its_dir(tmp_path: Path) -> None:
    sink = LocalSink(tmp_path / "results")
    with pytest.raises(ValueError):
        sink.put("default", "../../evil", "x")
    assert not (tmp_path / "evil.txt").exists()


def test_local_store_round_trip(tmp_path: Path) -> None:
    store = LocalJobStore(tmp_path)
    store.enqueue(Job(id="j1", prompt="hi"))
    job = store.claim_next("default")
    assert job is not None and job.status == "running"
    assert store.claim_next("default") is None  # already claimed
    store.complete(job, "ref")
    assert '"status": "done"' in (tmp_path / "default__j1.json").read_text(encoding="utf-8")


class _FakeTable:
    """A partition whose query returns 1 item per page, oldest (done) first."""

    def __init__(self, items: list[dict]) -> None:
        self.items = items
        self.updated: list[str] = []

    def query(self, **kwargs):
        start = kwargs.get("ExclusiveStartKey", {}).get("i", 0)
        page = self.items[start : start + 1]
        # mimic FilterExpression(status = queued) being applied after reading
        resp = {"Items": [dict(it) for it in page if it["status"] == "queued"]}
        if start + 1 < len(self.items):
            resp["LastEvaluatedKey"] = {"i": start + 1}
        return resp

    def update_item(self, **kwargs):
        self.updated.append(kwargs["Key"]["id"])


def test_dynamo_claim_pages_past_done_jobs() -> None:
    """Regression for #2: queued jobs behind many done jobs must still be found."""
    pytest.importorskip("boto3")
    items = [{"owner": "o", "id": f"done{i}", "status": "done"} for i in range(30)]
    items.append({"owner": "o", "id": "new", "status": "queued"})
    store = DynamoJobStore.__new__(DynamoJobStore)
    store.table = _FakeTable(items)
    job = store.claim_next("o")
    assert job is not None and job.id == "new"
