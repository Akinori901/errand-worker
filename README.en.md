# errand-worker

[日本語](README.md) | **English**

**Turn Claude Code into a self-hosted, asynchronous AI worker.**

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white">
  <img alt="Claude Code" src="https://img.shields.io/badge/Claude_Code-subscription-D97757">
  <img alt="Local-first" src="https://img.shields.io/badge/local--first-no_cloud_required-2ea44f">
  <img alt="Storage adapters" src="https://img.shields.io/badge/adapters-LocalFile_/_DynamoDB_/_S3-232F3E?logo=amazonwebservices&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-green">
</p>

Enqueue an *errand* (a prompt — optionally with a codebase to read); a small
worker running on your machine, **under your Claude subscription**, processes it
and writes the result. Your web app just drops jobs on a queue and reads results.

```
[your web app] --enqueue--> [queue] <--poll-- [errand-worker] --claude -p--> [result]
                              │                     (your Mac, your subscription)
              LocalFile (default, no cloud)
              DynamoDB / … (adapters)
```

## Why

- **Subscription, not API keys.** It shells out to the local `claude` CLI (Claude
  Code), which runs under your logged-in subscription. No `ANTHROPIC_API_KEY`, no
  per-token billing — build AI features on a flat rate.
- **Local-first.** The default job store is plain files and the default sink is a
  local directory. `git clone`, run, and it works — **no AWS account required.**
- **Keeps code local.** A job can point at a codebase (`cwd`); Claude reads it
  **on your machine** with read-only tools. The source never leaves for a cloud
  API — useful when an NDA forbids sending client code to third-party APIs.
- **Simple async job pattern.** Web → queue → worker → result. Swap the queue
  (files / DynamoDB / your own) and the sink (dir / S3 / your own) via small
  adapters.

## ⚠️ Terms of use

`errand-worker` is meant for **an individual running jobs for themselves** on
their own Claude Code environment. Using a Claude subscription as the generation
engine of a **SaaS served to third parties** may violate Anthropic's terms of
service. Check the current terms before doing that.

## Requirements

- Python 3.10+
- The `claude` CLI (Claude Code) installed and logged in, on your `PATH`
  (`claude --version` should work).

## Quickstart (60 seconds, no cloud)

```bash
git clone https://github.com/Akinori901/errand-worker
cd errand-worker

# 1. enqueue an errand
python -m errand_worker enqueue "Say exactly: hello from errand-worker"

# 2. process one job (invokes your local claude)
python -m errand_worker once

# 3. read the result
cat .errand/results/default/*.txt
```

Point a job at a codebase so Claude can ground its answer in real code:

```bash
python -m errand_worker enqueue "Summarise what this repo does in 2 lines" --cwd "$(pwd)"
python -m errand_worker once
```

Run it as a daemon (polls forever; keep it alive with launchd/systemd):

```bash
python -m errand_worker run
```

## The job contract

A queue item is just JSON:

```json
{
  "id": "unique-id",
  "owner": "default",
  "status": "queued",           // queued -> running -> done | error
  "prompt": "…",
  "cwd": "/path/to/code",        // optional: a codebase Claude may read
  "model": "opus",              // optional
  "result_ref": null,            // filled on done: where the result was written
  "error": null
}
```

Your web backend enqueues by writing such an item to the store; the worker does
the rest. To integrate a real web app, write items to the same store the worker
polls (files by default, or DynamoDB with `ERRAND_STORE=dynamodb`).

## Configuration (env / `.env`)

| Variable | Default | Meaning |
|---|---|---|
| `ERRAND_OWNER` | `default` | partition key — lets one queue serve many users/apps |
| `ERRAND_STORE` | `local` | `local` (files) or `dynamodb` |
| `ERRAND_SINK` | `local` | `local` (dir) or `s3` |
| `ERRAND_LOCAL_STORE` | `.errand/jobs` | local queue dir |
| `ERRAND_RESULTS_DIR` | `.errand/results` | local results dir |
| `ERRAND_JOBS_TABLE` | `errand-jobs` | DynamoDB table (store=dynamodb) |
| `ERRAND_S3_BUCKET` | — | S3 bucket (sink=s3) |
| `ERRAND_POLL_INTERVAL` | `5` | seconds between polls when idle |
| `ERRAND_CLAUDE_BIN` | `claude` | path to the Claude Code CLI |
| `ERRAND_DEFAULT_MODEL` | `sonnet` | model when a job omits one |
| `ERRAND_CLAUDE_CWD` | — | default codebase root (a job's own `cwd` overrides) |
| `ERRAND_CLAUDE_TIMEOUT` | `900` | per-job claude timeout (s) |
| `AWS_REGION` / `AWS_PROFILE` | `us-east-1` / — | for the AWS adapters |

DynamoDB table key schema: partition key `owner` (S), sort key `id` (S).
Install the AWS adapters with `pip install errand-worker[aws]`.

## Always-on (macOS launchd)

See [`examples/com.errand.worker.plist`](examples/com.errand.worker.plist).
A systemd unit for Linux is in [`examples/errand-worker.service`](examples/errand-worker.service).

## License

MIT
