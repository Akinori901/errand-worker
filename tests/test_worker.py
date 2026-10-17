from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from errand_worker import worker
from errand_worker.sink import LocalSink
from errand_worker.store import Job, LocalJobStore


def _completed(stdout: str = "answer") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


# --- command line ------------------------------------------------------------


def test_prompt_is_never_on_the_command_line(make_config) -> None:
    job = Job(id="j1", prompt="--dangerously-skip-permissions do things")
    args = worker.build_args(make_config(), job, cwd=None)
    assert job.prompt not in args


def test_codebase_job_gets_read_only_tools(make_config, tmp_path: Path) -> None:
    args = worker.build_args(make_config(), Job(id="j1"), cwd=str(tmp_path))
    assert args[args.index("--tools") + 1] == "Read,Glob,Grep"
    assert "--max-turns" in args


def test_text_job_gets_no_tools(make_config) -> None:
    args = worker.build_args(make_config(), Job(id="j1"), cwd=None)
    assert args[args.index("--tools") + 1] == ""


def test_mcp_and_project_settings_are_not_loaded(make_config) -> None:
    args = worker.build_args(make_config(), Job(id="j1"), cwd=None)
    assert "--strict-mcp-config" in args
    assert args[args.index("--setting-sources") + 1] == "user"


def test_job_model_overrides_default(make_config) -> None:
    args = worker.build_args(make_config(), Job(id="j1", model="opus"), cwd=None)
    assert args[args.index("--model") + 1] == "opus"


# --- running claude ------------------------------------------------------------


def test_prompt_is_sent_on_stdin(make_config) -> None:
    with mock.patch.object(worker.subprocess, "run", return_value=_completed()) as run:
        worker.run_claude(make_config(), Job(id="j1", prompt="hello"))
    assert run.call_args.kwargs["input"] == "hello"


def test_text_job_runs_in_an_empty_temp_dir(make_config, tmp_path: Path) -> None:
    seen: dict[str, list[str]] = {}

    def fake_run(args, **kwargs):
        seen["entries"] = [p.name for p in Path(kwargs["cwd"]).iterdir()]
        seen["cwd"] = [kwargs["cwd"]]
        return _completed()

    with mock.patch.object(worker.subprocess, "run", side_effect=fake_run):
        worker.run_claude(make_config(), Job(id="j1", prompt="hi"))
    assert seen["entries"] == []
    assert not Path(seen["cwd"][0]).exists()  # cleaned up afterwards


def test_failed_run_raises(make_config) -> None:
    failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
    with mock.patch.object(worker.subprocess, "run", return_value=failed), pytest.raises(RuntimeError):
        worker.run_claude(make_config(), Job(id="j1", prompt="hi"))


# --- cwd allow-list ----------------------------------------------------------


def test_cwd_inside_allowed_root_is_used(make_config, tmp_path: Path) -> None:
    repo = tmp_path / "repos" / "proj"
    repo.mkdir(parents=True)
    cfg = make_config(allowed_roots=[tmp_path / "repos"])
    assert worker.resolve_cwd(cfg, Job(id="j1", cwd=str(repo))) == str(repo.resolve())


@pytest.mark.parametrize("escape", ["/", "repos/../outside", "repos/link"])
def test_cwd_outside_allowed_root_is_rejected(make_config, tmp_path: Path, escape: str) -> None:
    (tmp_path / "repos").mkdir()
    (tmp_path / "outside").mkdir()
    (tmp_path / "repos" / "link").symlink_to(tmp_path / "outside")
    cfg = make_config(allowed_roots=[tmp_path / "repos"])
    target = escape if escape == "/" else str(tmp_path / escape)
    with pytest.raises(ValueError):
        worker.resolve_cwd(cfg, Job(id="j1", cwd=target))


def test_job_cannot_choose_cwd_when_no_roots(make_config, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        worker.resolve_cwd(make_config(), Job(id="j1", cwd=str(tmp_path)))


def test_default_cwd_is_used_when_job_has_none(make_config, tmp_path: Path) -> None:
    cfg = make_config(claude_cwd=tmp_path)
    assert worker.resolve_cwd(cfg, Job(id="j1")) == str(tmp_path)


# --- end to end with the local store / sink -----------------------------------


def test_poll_once_processes_a_job(make_config, tmp_path: Path) -> None:
    cfg = make_config()
    store = LocalJobStore(cfg.local_store_dir)
    sink = LocalSink(cfg.results_dir)
    store.enqueue(Job(id="j1", prompt="hi"))
    with mock.patch.object(worker.subprocess, "run", return_value=_completed("result!")):
        assert worker.poll_once(cfg, store, sink, worker._identity) is True
    assert (cfg.results_dir / "default" / "j1.txt").read_text(encoding="utf-8") == "result!"
    assert worker.poll_once(cfg, store, sink, worker._identity) is False


def test_unsafe_job_fails_without_running_claude(make_config) -> None:
    cfg = make_config()
    store = mock.Mock()
    store.claim_next.return_value = Job(id="../escape", prompt="hi")
    with mock.patch.object(worker.subprocess, "run") as run:
        worker.poll_once(cfg, store, LocalSink(cfg.results_dir), worker._identity)
    run.assert_not_called()
    store.fail.assert_called_once()
