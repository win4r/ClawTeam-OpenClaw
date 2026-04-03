<p align="center">
  <a href="README.md">English</a> |
  <a href="README_CN.md">简体中文</a> |
  <a href="README_TW.md">繁體中文</a> |
  <a href="README_JA.md">日本語</a> |
  <a href="README_KO.md">한국어</a> |
  <a href="README_FR.md">Français</a> |
  <a href="README_ES.md">Español</a> |
  <a href="README_DE.md">Deutsch</a> |
  <a href="README_IT.md">Italiano</a> |
  <a href="README_RU.md">Русский</a> |
  <a href="README_PT-BR.md">Português (Brasil)</a>
</p>

<h1 align="center">🦞ClawTeam-OpenClaw</h1>

<p align="center">
  <strong>CLIコーディングエージェントのためのマルチエージェントスワーム連携 — <a href="https://openclaw.ai">OpenClaw</a> をデフォルトに</strong>
</p>

<p align="center">
  <a href="https://github.com/HKUDS/ClawTeam"><img src="https://img.shields.io/badge/upstream-HKUDS%2FClawTeam-purple?style=for-the-badge" alt="Upstream"></a>
  <a href="#-クイックスタート"><img src="https://img.shields.io/badge/Quick_Start-3_min-blue?style=for-the-badge" alt="Quick Start"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/agents-OpenClaw_%7C_Claude_Code_%7C_Codex_%7C_nanobot-blueviolet" alt="Agents">
  <img src="https://img.shields.io/badge/transport-File_%7C_ZeroMQ_P2P-orange" alt="Transport">
  <img src="https://img.shields.io/badge/version-0.3.0-teal" alt="Version">
</p>

> **[HKUDS/ClawTeam](https://github.com/HKUDS/ClawTeam) のフォーク** — OpenClaw との深い統合を実現：デフォルトの `openclaw` エージェント、エージェントごとのセッション分離、実行承認の自動設定、本番環境対応のスポーンバックエンドを搭載。上流の修正はすべて同期されます。

目標を設定するだけ。エージェントスワームが残りを処理します — ワーカーの生成、タスクの分割、連携、結果の統合まですべて自動です。

[OpenClaw](https://openclaw.ai)（デフォルト）、[Claude Code](https://claude.ai/claude-code)、[Codex](https://openai.com/codex)、[nanobot](https://github.com/HKUDS/nanobot)、[Cursor](https://cursor.com)、およびあらゆる CLI エージェントで動作します。

---

## なぜ ClawTeam なのか？

現在の AI エージェントは強力ですが、**孤立して**動作しています。ClawTeam を使えば、エージェントが自律的にチームを編成し、作業を分担し、コミュニケーションし、人間が細かく管理しなくても結果を収束させることができます。

| | ClawTeam | 他のマルチエージェントフレームワーク |
|---|---------|----------------------------|
| **使うのは誰か** | AI エージェント自身 | オーケストレーションコードを書く人間 |
| **セットアップ** | `pip install` + プロンプト1つ | Docker、クラウド API、YAML 設定ファイル |
| **インフラ** | ファイルシステム + tmux | Redis、メッセージキュー、データベース |
| **エージェント対応** | あらゆる CLI エージェント | フレームワーク固有のみ |
| **分離** | Git worktree（実ブランチ） | コンテナまたは仮想環境 |

---

## 仕組み

<table>
<tr>
<td width="33%">

### エージェントがエージェントを生成
リーダーが `clawteam spawn` を呼び出してワーカーを作成します。各ワーカーは独自の **Git worktree**、**tmux ウィンドウ**、**アイデンティティ**を持ちます。

```bash
clawteam spawn --team my-team \
  --agent-name worker1 \
  --task "Implement auth module"
```

</td>
<td width="33%">

### エージェント間の通信
ワーカーは受信箱を確認し、タスクを更新し、結果を報告します — すべてプロンプトに**自動注入**される CLI コマンドを通じて行われます。

```bash
clawteam task list my-team --owner me
clawteam inbox send my-team leader \
  "Auth done. All tests passing."
```

</td>
<td width="33%">

### あなたは見守るだけ
タイル表示の tmux ビューまたは Web UI からスワームを監視します。リーダーが連携を担当します。

```bash
clawteam board attach my-team
# Or web dashboard
clawteam board serve --port 8080
```

</td>
</tr>
</table>

---

## クイックスタート

### 方法 1: エージェントに任せる（推奨）

ClawTeam をインストールし、エージェントにプロンプトを与えます：

```
"Build a web app. Use clawteam to split the work across multiple agents."
```

エージェントが自動でチームを作成し、ワーカーを生成し、タスクを割り当て、連携を行います — すべて `clawteam` CLI を通じて。

### 方法 2: 手動で操作する

```bash
# Create a team
clawteam team spawn-team my-team -d "Build the auth module" -n leader

# Spawn workers — each gets a git worktree + tmux window
clawteam spawn --team my-team --agent-name alice --task "Implement OAuth2 flow"
clawteam spawn --team my-team --agent-name bob   --task "Write unit tests for auth"

# Watch them work
clawteam board attach my-team
```

### 対応エージェント

| エージェント | スポーンコマンド | ステータス |
|-------|--------------|--------|
| [OpenClaw](https://openclaw.ai) | `clawteam spawn tmux openclaw --team ...` | **デフォルト** |
| [Claude Code](https://claude.ai/claude-code) | `clawteam spawn tmux claude --team ...` | 完全対応 |
| [Codex](https://openai.com/codex) | `clawteam spawn tmux codex --team ...` | 完全対応 |
| [nanobot](https://github.com/HKUDS/nanobot) | `clawteam spawn tmux nanobot --team ...` | 完全対応 |
| [Cursor](https://cursor.com) | `clawteam spawn subprocess cursor --team ...` | 実験的 |
| カスタムスクリプト | `clawteam spawn subprocess python --team ...` | 完全対応 |

---

## インストール

### ステップ 1: 前提条件

ClawTeam には **Python 3.10+**、**tmux**、および少なくとも1つの CLI コーディングエージェント（OpenClaw、Claude Code、Codex など）が必要です。

**既にインストール済みのものを確認：**

```bash
python3 --version   # Need 3.10+
tmux -V             # Need any version
openclaw --version  # Or: claude --version / codex --version
```

**不足している前提条件のインストール：**

| ツール | macOS | Ubuntu/Debian |
|------|-------|---------------|
| Python 3.10+ | `brew install python@3.12` | `sudo apt update && sudo apt install python3 python3-pip` |
| tmux | `brew install tmux` | `sudo apt install tmux` |
| OpenClaw | `pip install openclaw` | `pip install openclaw` |

> OpenClaw の代わりに Claude Code や Codex を使用する場合は、それぞれのドキュメントに従ってインストールしてください。OpenClaw はデフォルトですが、必須ではありません。

### ステップ 2: ClawTeam のインストール

> **⚠️ `pip install clawteam` や `npm install -g clawteam` を直接実行しないでください：**
> - `pip install clawteam` は PyPI 上の上流バージョンをインストールし、デフォルトが `claude` で OpenClaw 向けの適応が含まれていません。
> - `npm install -g clawteam` は無関係のスクワッティングパッケージをインストールします（発行者 `a9logic`）。`clawteam --version` で "Coming Soon" と表示される場合は誤ったパッケージです。まず `npm uninstall -g clawteam` で削除してください。
>
> **以下の 3 つのコマンドを使用してください — clone 後の `pip install -e .` は必須です。PyPI からではなくローカルリポジトリからインストールします。**

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
pip install -e .    # ← 必須！ローカルリポジトリからインストール。pip install clawteam とは異なります
```

オプション — P2P トランスポート（ZeroMQ）：

```bash
pip install -e ".[p2p]"
```

### ステップ 3: ~/bin/clawteam シンボリックリンクの作成

生成されたエージェントは、pip の bin ディレクトリが PATH にない新しいシェルで実行されます。`~/bin` にシンボリックリンクを作成することで、`clawteam` が常に到達可能になります：

```bash
mkdir -p ~/bin
ln -sf "$(which clawteam)" ~/bin/clawteam
```

`which clawteam` が何も返さない場合は、バイナリを手動で見つけてください：

```bash
# Common locations:
# ~/.local/bin/clawteam
# /opt/homebrew/bin/clawteam
# /usr/local/bin/clawteam
# /Library/Frameworks/Python.framework/Versions/3.*/bin/clawteam
find / -name clawteam -type f 2>/dev/null | head -5
```

次に、`~/bin` が PATH に含まれていることを確認します — 含まれていない場合は `~/.zshrc` または `~/.bashrc` に以下を追加してください：

```bash
export PATH="$HOME/bin:$PATH"
```

### ステップ 4: OpenClaw スキルのインストール（OpenClaw ユーザーのみ）

スキルファイルは、OpenClaw エージェントに自然言語で ClawTeam の使い方を教えます。OpenClaw を使用していない場合は、このステップをスキップしてください。

```bash
mkdir -p ~/.openclaw/workspace/skills/clawteam
cp skills/openclaw/SKILL.md ~/.openclaw/workspace/skills/clawteam/SKILL.md
```

### ステップ 5: 実行承認の設定（OpenClaw ユーザーのみ）

生成された OpenClaw エージェントは、`clawteam` コマンドを実行するための許可が必要です。この設定がないと、エージェントがインタラクティブな許可プロンプトでブロックされます。

```bash
# Ensure security mode is "allowlist" (not "full")
python3 -c "
import json, pathlib
p = pathlib.Path.home() / '.openclaw' / 'exec-approvals.json'
if p.exists():
    d = json.loads(p.read_text())
    d.setdefault('defaults', {})['security'] = 'allowlist'
    p.write_text(json.dumps(d, indent=2))
    print('exec-approvals.json updated: security = allowlist')
else:
    print('exec-approvals.json not found — run openclaw once first, then re-run this step')
"

# Add clawteam to the allowlist (use the absolute path — OpenClaw 4.2+ requires it)
openclaw approvals allowlist add --agent "*" "$(which clawteam)"
```

> `openclaw approvals` が失敗する場合、OpenClaw ゲートウェイが起動していない可能性があります。先にゲートウェイを起動してからリトライしてください。

### ステップ 6: 動作確認

```bash
clawteam --version          # Should print version
clawteam config health      # Should show all green
```

OpenClaw を使用している場合は、スキルが読み込まれていることも確認してください：

```bash
openclaw skills list | grep clawteam
```

### 自動インストーラー

上記のステップ 2〜6 は、単一のスクリプトでも実行できます：

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
bash scripts/install-openclaw.sh
```

### トラブルシューティング

| 問題 | 原因 | 解決方法 |
|---------|-------|-----|
| `clawteam: command not found` | pip の bin ディレクトリが PATH にない | ステップ 3（シンボリックリンク + PATH）を実行 |
| 生成されたエージェントが `clawteam` を見つけられない | エージェントが pip の PATH なしの新しいシェルで実行される | `~/bin/clawteam` シンボリックリンクが存在し、`~/bin` が PATH にあることを確認 |
| `openclaw approvals` が失敗する | ゲートウェイが起動していない | 先に `openclaw gateway` を起動してから、ステップ 5 をリトライ |
| `exec-approvals.json not found` | OpenClaw が一度も実行されていない | `openclaw` を一度実行して設定を生成してから、ステップ 5 をリトライ |
| エージェントが許可プロンプトでブロックされる | 実行承認のセキュリティが "full" になっている | ステップ 5 を実行して "allowlist" に切り替え |
| `pip install -e .` が失敗する | ビルド依存関係が不足 | 先に `pip install hatchling` を実行 |
| `clawteam --version` が "Coming Soon" と表示される | npm のスクワッティングパッケージを誤ってインストール（`a9logic`、本プロジェクトとは無関係） | `npm uninstall -g clawteam` を実行し、ステップ 2 に従って再インストール |

---

## ユースケース

### 1. 自律型 ML 研究 — 8 エージェント x 8 GPU

[@karpathy/autoresearch](https://github.com/karpathy/autoresearch) に基づく。1つのプロンプトで 8 つの研究エージェントを H100 上に展開し、2000 以上の実験を自律的に設計します。

```
Human: "Use 8 GPUs to optimize train.py. Read program.md for instructions."

Leader agent:
├── Spawns 8 agents, each assigned a research direction (depth, width, LR, batch size...)
├── Each agent gets its own git worktree for isolated experiments
├── Every 30 min: checks results, cross-pollinates best configs to new agents
├── Reassigns GPUs as agents finish — fresh agents start from best known config
└── Result: val_bpb 1.044 → 0.977 (6.4% improvement) across 2430 experiments in ~30 GPU-hours
```

詳細な結果: [novix-science/autoresearch](https://github.com/novix-science/autoresearch)

### 2. エージェント駆動ソフトウェア開発

```
Human: "Build a full-stack todo app with auth, database, and React frontend."

Leader agent:
├── Creates tasks with dependency chains (API schema → auth + DB → frontend → tests)
├── Spawns 5 agents (architect, 2 backend, frontend, tester) in separate worktrees
├── Dependencies auto-resolve: architect completes → backend unblocks → tester unblocks
├── Agents coordinate via inbox: "Here's the OpenAPI spec", "Auth endpoints ready"
└── Leader merges all worktrees into main when complete
```

### 3. AI ヘッジファンド — テンプレート起動

TOML テンプレートで、1つのコマンドで完全な 7 エージェント投資チームを生成します：

```bash
clawteam launch hedge-fund --team fund1 --goal "Analyze AAPL, MSFT, NVDA for Q2 2026"
```

5 人のアナリストエージェント（バリュー、グロース、テクニカル、ファンダメンタルズ、センチメント）が並行して作業します。リスクマネージャーがすべてのシグナルを統合します。ポートフォリオマネージャーが最終判断を下します。

テンプレートは TOML ファイルです — あらゆるドメインに合わせて**独自のテンプレートを作成**できます。

---

## 機能

<table>
<tr>
<td width="50%">

### エージェントの自己組織化
- リーダーがワーカーを生成・管理
- 自動注入される連携プロンプト — 手動セットアップ不要
- ワーカーが自動でステータスとアイドル状態を報告
- あらゆる CLI エージェントが参加可能

### ワークスペース分離
- 各エージェントが独自の **Git worktree** を取得
- 並行エージェント間でマージコンフリクトなし
- チェックポイント、マージ、クリーンアップコマンド
- ブランチ命名規則: `clawteam/{team}/{agent}`

### 依存関係付きタスク管理
- 共有カンバン: `pending` → `in_progress` → `completed` / `blocked`
- `--blocked-by` チェーンと完了時の自動アンブロック
- `task wait` がすべてのタスク完了まで待機

</td>
<td width="50%">

### エージェント間メッセージング
- ポイントツーポイント受信箱（送信、受信、ピーク）
- 全チームメンバーへのブロードキャスト
- ファイルベース（デフォルト）または ZeroMQ P2P トランスポート

### モニタリングとダッシュボード
- `board show` — ターミナルカンバン
- `board live` — 自動更新ダッシュボード
- `board attach` — タイル表示の tmux ビュー
- `board serve` — リアルタイム更新の Web UI

### チームテンプレート
- TOML ファイルでチームのアーキタイプを定義（ロール、タスク、プロンプト）
- コマンド1つ: `clawteam launch <template>`
- 変数置換: `{goal}`、`{team_name}`、`{agent_name}`
- **エージェントごとのモデル割り当て**（プレビュー）: 異なるロールに異なるモデルを割り当て — [下記参照](#エージェントごとのモデル割り当てプレビュー)

</td>
</tr>
</table>

**その他:** プラン承認ワークフロー、グレースフルなライフサイクル管理、全コマンドで `--json` 出力、クロスマシン対応（NFS/SSHFS または P2P）、マルチユーザーネームスペース、自動ロールバック付きスポーン検証、並行安全のための `fcntl` ファイルロック。

---

## OpenClaw 統合

このフォークは [OpenClaw](https://openclaw.ai) を**デフォルトエージェント**にしています。ClawTeam なしでは、各 OpenClaw エージェントは孤立して動作します。ClawTeam がそれをマルチエージェントプラットフォームに変えます。

| 機能 | OpenClaw 単体 | OpenClaw + ClawTeam |
|-----------|---------------|-------------------|
| **タスク割り当て** | エージェントごとの手動メッセージング | リーダーが自律的に分割、割り当て、監視 |
| **並行開発** | 共有の作業ディレクトリ | エージェントごとに分離された Git worktree |
| **依存関係** | 手動ポーリング | `--blocked-by` と自動アンブロック |
| **コミュニケーション** | AGI リレー経由のみ | ダイレクトなポイントツーポイント受信箱 + ブロードキャスト |
| **可観測性** | ログの閲覧 | カンバンボード + タイル表示の tmux ビュー |

スキルをインストールしたら、任意のチャンネルで OpenClaw ボットに話しかけてください：

| あなたの発言 | 実行される処理 |
|-------------|-------------|
| 「5エージェントのチームを作ってウェブアプリを構築して」 | チーム、タスクを作成し、tmux で 5 エージェントを生成 |
| 「ヘッジファンド分析チームを起動して」 | 7 エージェントで `clawteam launch hedge-fund` を実行 |
| 「エージェントチームのステータスを確認して」 | カンバン出力で `clawteam board show` を実行 |

```
  You (Telegram/Discord/TUI)
         │
         ▼
  ┌──────────────────┐
  │  OpenClaw Gateway │  ← activates clawteam skill
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────┐     clawteam spawn     ┌─────────────────┐
  │  Leader Agent    │ ─────────────────────► │  openclaw tui   │
  │  (openclaw)      │ ──┐                    │  (tmux window)  │
  │                  │   │                    │  git worktree   │
  │  Manages swarm   │   ├──────────────────► ├─────────────────┤
  │  via clawteam    │   │                    │  openclaw tui   │
  │  CLI             │   ├──────────────────► ├─────────────────┤
  └──────────────────┘   │                    │  openclaw tui   │
                         └──────────────────► └─────────────────┘
                                               All coordinate via
                                               ~/.clawteam/ (tasks, inboxes)
```

---

## アーキテクチャ

```
  Human: "Optimize this LLM"
         │
         ▼
  ┌──────────────┐     clawteam spawn     ┌──────────────┐
  │  Leader      │ ──────────────────────► │  Worker      │
  │  (any agent) │ ──────┐                │  git worktree │
  │              │       ├──────────────► │  tmux window  │
  │  spawn       │       │                ├──────────────┤
  │  task create │       ├──────────────► │  Worker      │
  │  inbox send  │       │                │  git worktree │
  │  board show  │       └──────────────► │  tmux window  │
  └──────────────┘                        └──────────────┘
                                                 │
                                                 ▼
                                      ┌─────────────────────┐
                                      │    ~/.clawteam/     │
                                      │ ├── teams/   (who) │
                                      │ ├── tasks/   (what)│
                                      │ ├── inboxes/ (talk)│
                                      │ └── workspaces/    │
                                      └─────────────────────┘
```

すべてのステートは `~/.clawteam/` に JSON ファイルとして保存されます。データベースもサーバーも不要です。`fcntl` ファイルロックによるアトミック書き込みでクラッシュ安全性を確保しています。

| 設定 | 環境変数 | デフォルト値 |
|---------|---------|---------|
| データディレクトリ | `CLAWTEAM_DATA_DIR` | `~/.clawteam` |
| トランスポート | `CLAWTEAM_TRANSPORT` | `file` |
| ワークスペースモード | `CLAWTEAM_WORKSPACE` | `auto` |
| スポーンバックエンド | `CLAWTEAM_DEFAULT_BACKEND` | `tmux` |

---

## コマンドリファレンス

<details open>
<summary><strong>コアコマンド</strong></summary>

```bash
# Team lifecycle
clawteam team spawn-team <team> -d "description" -n <leader>
clawteam team discover                    # List all teams
clawteam team status <team>               # Show members
clawteam team cleanup <team> --force      # Delete team

# Spawn agents
clawteam spawn --team <team> --agent-name <name> --task "do this"
clawteam spawn tmux codex --team <team> --agent-name <name> --task "do this"

# Task management
clawteam task create <team> "subject" -o <owner> --blocked-by <id1>,<id2>
clawteam task update <team> <id> --status completed   # auto-unblocks dependents
clawteam task list <team> --status blocked --owner worker1
clawteam task wait <team> --timeout 300

# Messaging
clawteam inbox send <team> <to> "message"
clawteam inbox broadcast <team> "message"
clawteam inbox receive <team>             # consume messages
clawteam inbox peek <team>                # read without consuming

# Monitoring
clawteam board show <team>                # terminal kanban
clawteam board live <team> --interval 3   # auto-refresh
clawteam board attach <team>              # tiled tmux view
clawteam board serve --port 8080          # web UI
```

</details>

<details>
<summary><strong>ワークスペース、プラン、ライフサイクル、設定</strong></summary>

```bash
# Workspace (git worktree management)
clawteam workspace list <team>
clawteam workspace checkpoint <team> <agent>    # auto-commit
clawteam workspace merge <team> <agent>         # merge back to main
clawteam workspace cleanup <team> <agent>       # remove worktree

# Plan approval
clawteam plan submit <team> <agent> "plan" --summary "TL;DR"
clawteam plan approve <team> <plan-id> <agent> --feedback "LGTM"
clawteam plan reject <team> <plan-id> <agent> --feedback "Revise X"

# Lifecycle
clawteam lifecycle request-shutdown <team> <agent> --reason "done"
clawteam lifecycle approve-shutdown <team> <request-id> <agent>
clawteam lifecycle idle <team>

# Templates
clawteam launch <template> --team <name> --goal "Build X"
clawteam template list

# Config
clawteam config show
clawteam config set transport p2p
clawteam config health
```

</details>

---

## エージェントごとのモデル割り当て（プレビュー）

> **ブランチ:** [`feat/per-agent-model-assignment`](https://github.com/win4r/ClawTeam-OpenClaw/tree/feat/per-agent-model-assignment)
>
> この機能は、別ブランチで早期テスト向けに公開されています。OpenClaw の `--model` フラグがリリースされ次第、`main` にマージされる予定です。

マルチエージェントスワームにおいて、コストとパフォーマンスのトレードオフを最適化するために、異なるエージェントロールに異なるモデルを割り当てます。

```bash
# Install from the feature branch
pip install -e "git+https://github.com/win4r/ClawTeam-OpenClaw.git@feat/per-agent-model-assignment#egg=clawteam"
```

**テンプレートでのエージェントごとのモデル指定：**
```toml
[template]
name = "my-team"
command = ["openclaw"]
model = "sonnet-4.6"              # default for all agents
model_strategy = "auto"           # or: leaders→strong, workers→balanced

[template.leader]
name = "lead"
model = "opus"                    # override for leader

[[template.agents]]
name = "worker"
model_tier = "cheap"              # cost tiers: strong / balanced / cheap
```

**CLI フラグ：**
```bash
clawteam spawn --model opus                          # single agent
clawteam launch my-template --model gpt-5.4          # override all agents
clawteam launch my-template --model-strategy auto     # auto-assign by role
```

詳細は [issue #1](https://github.com/win4r/ClawTeam-OpenClaw/issues/1) で機能リクエストとディスカッションを参照してください。

---

## ロードマップ

| バージョン | 内容 | ステータス |
|---------|------|--------|
| v0.3 | ファイル + P2P トランスポート、Web UI、マルチユーザー、テンプレート | リリース済み |
| v0.4 | Redis トランスポート — クロスマシンメッセージング | 計画中 |
| v0.5 | 共有ステートレイヤー — マシン間のチーム設定 | 計画中 |
| v0.6 | エージェントマーケットプレイス — コミュニティテンプレート | 検討中 |
| v0.7 | アダプティブスケジューリング — 動的タスク再割り当て | 検討中 |
| v1.0 | プロダクショングレード — 認証、権限、監査ログ | 検討中 |

---

## コントリビューション

コントリビューションを歓迎します：

- **エージェント統合** — より多くの CLI エージェントのサポート
- **チームテンプレート** — 新しいドメイン向けの TOML テンプレート
- **トランスポートバックエンド** — Redis、NATS など
- **ダッシュボード改善** — Web UI、Grafana
- **ドキュメント** — チュートリアルとベストプラクティス

---

## 謝辞

- [@karpathy/autoresearch](https://github.com/karpathy/autoresearch) — 自律型 ML 研究フレームワーク
- [OpenClaw](https://openclaw.ai) — デフォルトエージェントバックエンド
- [Claude Code](https://claude.ai/claude-code) および [Codex](https://openai.com/codex) — 対応 AI コーディングエージェント
- [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) — ヘッジファンドテンプレートのインスピレーション
- [CLI-Anything](https://github.com/HKUDS/CLI-Anything) — 姉妹プロジェクト

## ライセンス

MIT — 自由に使用、改変、再配布できます。

---

<div align="center">

**ClawTeam** — *エージェントスワームインテリジェンス。*

</div>
