"""処理中にワーカーが落ちて running のまま残ったジョブを回収する。"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from unittest import mock

import pytest

from errand_worker import worker
from errand_worker.config import _stale_after
from errand_worker.sink import LocalSink
from errand_worker.store import DynamoJobStore, Job, LocalJobStore

OLD = "2026-01-01T00:00:00Z"
STALE_BEFORE = "2026-01-01T00:10:00Z"
FRESH = "2026-01-01T00:20:00Z"


def _write(store: LocalJobStore, job: Job) -> None:
    # _save は updated_at を現在時刻で上書きするので、テスト用に直接書く
    import json
    from dataclasses import asdict

    store._path(job).write_text(json.dumps(asdict(job)), encoding="utf-8")


# --- LocalJobStore -----------------------------------------------------------


def test_queued_is_claimed_and_counts_an_attempt(tmp_path: Path) -> None:
    store = LocalJobStore(tmp_path)
    store.enqueue(Job(id="j1"))
    job = store.claim_next("default", STALE_BEFORE)
    assert job is not None and job.status == "running" and job.attempts == 1


def test_stale_running_job_is_reclaimed(tmp_path: Path) -> None:
    store = LocalJobStore(tmp_path)
    _write(store, Job(id="j1", status="running", updated_at=OLD, attempts=1))
    job = store.claim_next("default", STALE_BEFORE)
    assert job is not None and job.id == "j1" and job.attempts == 2


def test_running_job_that_is_still_fresh_is_left_alone(tmp_path: Path) -> None:
    store = LocalJobStore(tmp_path)
    _write(store, Job(id="j1", status="running", updated_at=FRESH, attempts=1))
    assert store.claim_next("default", STALE_BEFORE) is None


def test_running_jobs_are_not_reclaimed_without_a_threshold(tmp_path: Path) -> None:
    store = LocalJobStore(tmp_path)
    _write(store, Job(id="j1", status="running", updated_at=OLD, attempts=1))
    assert store.claim_next("default") is None


@pytest.mark.parametrize("status", ["done", "error"])
def test_finished_jobs_are_never_reclaimed(tmp_path: Path, status: str) -> None:
    store = LocalJobStore(tmp_path)
    _write(store, Job(id="j1", status=status, updated_at=OLD))
    assert store.claim_next("default", STALE_BEFORE) is None


# --- poll_once ---------------------------------------------------------------


def test_job_that_keeps_crashing_is_given_up(make_config) -> None:
    cfg = make_config(max_attempts=3)
    store = LocalJobStore(cfg.local_store_dir)
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    _write(store, Job(id="j1", status="running", updated_at=old, attempts=3))
    with mock.patch.object(worker.subprocess, "run") as run:
        assert worker.poll_once(cfg, store, LocalSink(cfg.results_dir), worker._identity) is True
    run.assert_not_called()
    saved = store._path(Job(id="j1")).read_text(encoding="utf-8")
    assert '"status": "error"' in saved and "gave up after 3 attempts" in saved


def test_reclaimed_job_is_processed_again(make_config) -> None:
    cfg = make_config()
    store = LocalJobStore(cfg.local_store_dir)
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    _write(store, Job(id="j1", status="running", updated_at=old, attempts=1, prompt="hi"))
    done = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    with mock.patch.object(worker.subprocess, "run", return_value=done):
        worker.poll_once(cfg, store, LocalSink(cfg.results_dir), worker._identity)
    assert (cfg.results_dir / "default" / "j1.txt").read_text(encoding="utf-8") == "ok"


# --- config ------------------------------------------------------------------


def test_stale_after_defaults_to_timeout_plus_five_minutes() -> None:
    assert _stale_after(None, 900) == 1200


@pytest.mark.parametrize("raw", ["900", "600"])
def test_stale_after_must_exceed_the_claude_timeout(raw: str) -> None:
    with pytest.raises(ValueError):
        _stale_after(raw, 900)


# --- DynamoJobStore ----------------------------------------------------------


class _RecordingTable:
    def __init__(self, items: list[dict]) -> None:
        self.items = items
        self.updates: list[dict] = []

    def query(self, **kwargs):
        self.filter = kwargs["FilterExpression"]
        return {"Items": [dict(it) for it in self.items]}

    def update_item(self, **kwargs):
        self.updates.append(kwargs)


def _expression(cond) -> str:
    from boto3.dynamodb.conditions import ConditionExpressionBuilder

    built = ConditionExpressionBuilder().build_expression(cond)
    names = built.attribute_name_placeholders
    values = built.attribute_value_placeholders
    text = built.condition_expression
    for k, v in {**names, **{k: repr(v) for k, v in values.items()}}.items():
        text = text.replace(k, str(v))
    return text


def test_dynamo_reclaim_is_guarded_by_the_updated_at_it_read() -> None:
    """2 台のワーカーが同じ放置ジョブを同時に回収しないこと。"""
    pytest.importorskip("boto3")
    store = DynamoJobStore.__new__(DynamoJobStore)
    store.table = _RecordingTable([{"owner": "o", "id": "j1", "status": "running", "updated_at": OLD}])
    job = store.claim_next("o", STALE_BEFORE)
    assert job is not None and job.attempts == 1
    cond = _expression(store.table.updates[0]["ConditionExpression"])
    assert "status = 'running'" in cond and f"updated_at = '{OLD}'" in cond
    assert "ADD attempts" in store.table.updates[0]["UpdateExpression"]
    assert "updated_at < " in _expression(store.table.filter)


def test_dynamo_does_not_look_at_running_jobs_without_a_threshold() -> None:
    pytest.importorskip("boto3")
    store = DynamoJobStore.__new__(DynamoJobStore)
    store.table = _RecordingTable([{"owner": "o", "id": "j1", "status": "queued"}])
    store.claim_next("o")
    assert _expression(store.table.filter) == "status = 'queued'"
