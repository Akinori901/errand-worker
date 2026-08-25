"""CLI entrypoint.

  python -m errand_worker run                 # poll forever (the daemon)
  python -m errand_worker once                # process one job then exit
  python -m errand_worker enqueue "<prompt>"  # local-store test helper
      [--cwd PATH] [--model NAME] [--id ID]

The daemon (``run``) is what a process manager (launchd/systemd) keeps alive.
"""
from __future__ import annotations

import sys
import time
import uuid

from .config import Config
from .sink import LocalSink, S3Sink, Sink
from .store import DynamoJobStore, Job, JobStore, LocalJobStore
from .worker import poll_once, run_forever


def build_store(cfg: Config) -> JobStore:
    if cfg.store == "dynamodb":
        return DynamoJobStore(cfg.jobs_table, cfg.aws_region, cfg.aws_profile)
    return LocalJobStore(cfg.local_store_dir)


def build_sink(cfg: Config) -> Sink:
    if cfg.sink == "s3":
        return S3Sink(cfg.s3_bucket, cfg.aws_region, cfg.aws_profile)
    return LocalSink(cfg.results_dir)


def _enqueue(cfg: Config, argv: list[str]) -> int:
    if cfg.store != "local":
        print("enqueue helper only supports ERRAND_STORE=local", file=sys.stderr)
        return 2
    if not argv:
        print('usage: enqueue "<prompt>" [--cwd PATH] [--model NAME] [--id ID]', file=sys.stderr)
        return 2
    prompt = argv[0]
    opts = argv[1:]
    kw: dict[str, str] = {}
    it = iter(opts)
    for flag in it:
        if flag in ("--cwd", "--model", "--id"):
            kw[flag.lstrip("-")] = next(it, "")
    job = Job(
        id=kw.get("id") or uuid.uuid4().hex,
        owner=cfg.owner,
        prompt=prompt,
        cwd=kw.get("cwd") or None,
        model=kw.get("model") or None,
    )
    store = LocalJobStore(cfg.local_store_dir)
    store.enqueue(job)
    print(f"enqueued job {job.id} (owner={job.owner}) at {cfg.local_store_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "run"
    cfg = Config.load()

    if cmd == "run":
        run_forever(cfg, build_store(cfg), build_sink(cfg))
        return 0
    if cmd == "once":
        handled = poll_once(cfg, build_store(cfg), build_sink(cfg), lambda _j, p: p)
        print("processed 1 job" if handled else "no queued jobs")
        return 0
    if cmd == "enqueue":
        return _enqueue(cfg, argv[1:])

    print(f"unknown command: {cmd}", file=sys.stderr)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
