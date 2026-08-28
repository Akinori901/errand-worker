# errand-worker

**日本語** | [English](README.en.md)

**Claude Code を、自前ホストの非同期 AI ワーカーにする。**

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white">
  <img alt="Claude Code" src="https://img.shields.io/badge/Claude_Code-subscription-D97757">
  <img alt="Local-first" src="https://img.shields.io/badge/local--first-no_cloud_required-2ea44f">
  <img alt="Storage adapters" src="https://img.shields.io/badge/adapters-LocalFile_/_DynamoDB_/_S3-232F3E?logo=amazonwebservices&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-green">
</p>

*用事（errand）* — プロンプト、必要なら読ませたいコードベース付き — をキューに積むと、
手元のマシンで動く小さなワーカーが **あなたの Claude サブスクリプションで** それを処理し、
結果を書き出します。Web アプリ側はキューにジョブを置き、結果を読むだけです。

```
[あなたのWebアプリ] --積む--> [キュー] <--取得-- [errand-worker] --claude -p--> [結果]
                                │                  （あなたのMac／あなたのサブスク）
              LocalFile（既定・クラウド不要）
              DynamoDB / …（アダプタ）
```

## 何が嬉しいか

- **APIキーではなくサブスクリプション。** ローカルの `claude` CLI（Claude Code）を
  呼び出すので、ログイン済みのサブスクリプションで動きます。`ANTHROPIC_API_KEY` は不要、
  トークン従量課金もありません — **定額のまま AI 機能を作れます。**
- **ローカル完結が既定。** ジョブの保管先は素のファイル、結果の出力先はローカルの
  ディレクトリです。`git clone` してすぐ動きます — **AWS アカウントは不要です。**
- **コードを外に出さない。** ジョブにはコードベース（`cwd`）を指定でき、Claude は
  **あなたのマシン上で** 読み取り専用ツールを使って読みます。ソースがクラウドの API へ
  送られることはありません — 顧客コードの外部送信を NDA が禁じている場合に有効です。
- **素直な非同期ジョブ構成。** Web → キュー → ワーカー → 結果。キュー（ファイル /
  DynamoDB / 自作）も出力先（ディレクトリ / S3 / 自作）も、小さなアダプタで差し替えられます。

## ⚠️ 利用規約について

`errand-worker` は **個人が自分の Claude Code 環境で、自分のためにジョブを処理する**
用途を想定しています。Claude のサブスクリプションを **第三者に提供する SaaS の生成エンジン**
として使うことは、Anthropic の利用規約に抵触する可能性があります。
そうした使い方をする前に、必ず最新の規約を確認してください。

## 必要なもの

- Python 3.10 以上
- `claude` CLI（Claude Code）がインストール済み・ログイン済みで `PATH` にあること
  （`claude --version` が通ること）

## クイックスタート（60秒・クラウド不要）

```bash
git clone https://github.com/Akinori901/errand-worker
cd errand-worker

# 1. 用事を積む
python -m errand_worker enqueue "「hello from errand-worker」とだけ返して"

# 2. 1件だけ処理する（ローカルの claude が呼ばれる）
python -m errand_worker once

# 3. 結果を読む
cat .errand/results/default/*.txt
```

コードベースを指定すれば、実際のコードに基づいて答えさせられます:

```bash
python -m errand_worker enqueue "このリポジトリが何をするものか2行で説明して" --cwd "$(pwd)"
python -m errand_worker once
```

常駐させる（ポーリングし続けます。launchd / systemd で生かしておいてください）:

```bash
python -m errand_worker run
```

## ジョブの形式

キューの1件は、ただの JSON です:

```json
{
  "id": "unique-id",
  "owner": "default",
  "status": "queued",           // queued -> running -> done | error
  "prompt": "…",
  "cwd": "/path/to/code",        // 任意: Claude に読ませるコードベース
  "model": "opus",              // 任意
  "result_ref": null,            // 完了時に埋まる: 結果の書き出し先
  "error": null
}
```

Web バックエンドはこの形式の項目を保管先へ書き込むだけで、あとはワーカーが処理します。
実際の Web アプリと繋ぐときは、**ワーカーがポーリングしているのと同じ保管先** へ
書き込んでください（既定はファイル、`ERRAND_STORE=dynamodb` なら DynamoDB）。

## 設定（環境変数 / `.env`）

| 変数 | 既定値 | 意味 |
|---|---|---|
| `ERRAND_OWNER` | `default` | パーティションキー。1つのキューを複数ユーザ/アプリで共有できる |
| `ERRAND_STORE` | `local` | `local`（ファイル）または `dynamodb` |
| `ERRAND_SINK` | `local` | `local`（ディレクトリ）または `s3` |
| `ERRAND_LOCAL_STORE` | `.errand/jobs` | ローカルキューのディレクトリ |
| `ERRAND_RESULTS_DIR` | `.errand/results` | ローカル結果のディレクトリ |
| `ERRAND_JOBS_TABLE` | `errand-jobs` | DynamoDB のテーブル名（store=dynamodb のとき） |
| `ERRAND_S3_BUCKET` | — | S3 バケット名（sink=s3 のとき） |
| `ERRAND_POLL_INTERVAL` | `5` | 空のときのポーリング間隔（秒） |
| `ERRAND_CLAUDE_BIN` | `claude` | Claude Code CLI のパス |
| `ERRAND_DEFAULT_MODEL` | `sonnet` | ジョブがモデル未指定のときの既定 |
| `ERRAND_CLAUDE_CWD` | — | 既定のコードベース（ジョブ側の `cwd` が優先） |
| `ERRAND_CLAUDE_TIMEOUT` | `900` | 1ジョブあたりの claude 実行上限（秒） |
| `AWS_REGION` / `AWS_PROFILE` | `us-east-1` / — | AWS アダプタ用 |

DynamoDB のキー構成: パーティションキー `owner`（S）、ソートキー `id`（S）。
AWS アダプタは `pip install errand-worker[aws]` で入ります。

## 常駐させる（macOS launchd）

[`examples/com.errand.worker.plist`](examples/com.errand.worker.plist) を参照してください。
Linux 向けの systemd ユニットは
[`examples/errand-worker.service`](examples/errand-worker.service) にあります。

## ライセンス

MIT
