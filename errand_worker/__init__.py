"""errand-worker: turn Claude Code into a self-hosted async AI worker.

Enqueue a job (a prompt, optionally a codebase to read); a local worker running
under your Claude subscription processes it and writes the result. No API key.
"""
from .config import Config
from .sink import LocalSink, S3Sink, Sink
from .store import DynamoJobStore, Job, JobStore, LocalJobStore
from .worker import poll_once, process, run_claude, run_forever

__version__ = "0.1.0"

__all__ = [
    "Config",
    "Job",
    "JobStore",
    "LocalJobStore",
    "DynamoJobStore",
    "Sink",
    "LocalSink",
    "S3Sink",
    "run_claude",
    "process",
    "poll_once",
    "run_forever",
]
