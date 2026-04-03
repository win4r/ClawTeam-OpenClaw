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
  <strong>面向命令列程式碼智能體的多智能體集群協作 — 預設使用 <a href="https://openclaw.ai">OpenClaw</a></strong>
</p>

<p align="center">
  <a href="https://github.com/HKUDS/ClawTeam"><img src="https://img.shields.io/badge/upstream-HKUDS%2FClawTeam-purple?style=for-the-badge" alt="Upstream"></a>
  <a href="#-快速開始"><img src="https://img.shields.io/badge/Quick_Start-3_min-blue?style=for-the-badge" alt="Quick Start"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/agents-OpenClaw_%7C_Claude_Code_%7C_Codex_%7C_nanobot-blueviolet" alt="Agents">
  <img src="https://img.shields.io/badge/transport-File_%7C_ZeroMQ_P2P-orange" alt="Transport">
  <img src="https://img.shields.io/badge/version-0.3.0-teal" alt="Version">
</p>

> **[HKUDS/ClawTeam](https://github.com/HKUDS/ClawTeam) 的分叉版本**，深度整合 OpenClaw：預設使用 `openclaw` 智能體、每個智能體獨立會話隔離、執行授權自動配置，以及經過生產環境驗證的啟動後端。所有上游修復均已同步。

您設定目標，智能體集群處理剩下的一切 — 啟動工作者、拆分任務、協調配合、合併結果。

支援 [OpenClaw](https://openclaw.ai)（預設）、[Claude Code](https://claude.ai/claude-code)、[Codex](https://openai.com/codex)、[nanobot](https://github.com/HKUDS/nanobot)、[Cursor](https://cursor.com) 及任何命令列智能體。

---

## 為什麼選擇 ClawTeam？

當前的人工智慧智能體功能強大，但都在**孤立**運作。ClawTeam 讓智能體自組織為團隊 — 拆分工作、互相溝通、匯聚結果，無需人類事必躬親。

| | ClawTeam | 其他多智能體框架 |
|---|---------|----------------------------|
| **誰在使用** | 人工智慧智能體自身 | 人類編寫編排程式碼 |
| **設定** | `pip install` + 一句提示詞 | Docker、雲端 API、YAML 設定檔 |
| **基礎設施** | 檔案系統 + tmux | Redis、訊息佇列、資料庫 |
| **智能體支援** | 任何命令列智能體 | 僅限特定框架 |
| **隔離方式** | Git worktrees（真實分支） | 容器或虛擬環境 |

---

## 運作原理

<table>
<tr>
<td width="33%">

### 智能體啟動智能體
領導者呼叫 `clawteam spawn` 建立工作者。每個工作者都擁有獨立的 **git worktree**、**tmux 視窗**和**身份標識**。

```bash
clawteam spawn --team my-team \
  --agent-name worker1 \
  --task "Implement auth module"
```

</td>
<td width="33%">

### 智能體之間互相對話
工作者檢查收件匣、更新任務、回報結果 — 全部透過**自動注入**提示詞的命令列指令完成。

```bash
clawteam task list my-team --owner me
clawteam inbox send my-team leader \
  "Auth done. All tests passing."
```

</td>
<td width="33%">

### 您只需觀看
透過分割式 tmux 檢視或 Web 介面監控集群。領導者負責協調一切。

```bash
clawteam board attach my-team
# Or web dashboard
clawteam board serve --port 8080
```

</td>
</tr>
</table>

---

## 快速開始

### 方式一：讓智能體自行驅動（推薦）

安裝 ClawTeam，然後向您的智能體發出提示：

```
"Build a web app. Use clawteam to split the work across multiple agents."
```

智能體自動建立團隊、啟動工作者、分配任務並協調 — 全部透過 `clawteam` 命令列完成。

### 方式二：手動驅動

```bash
# Create a team
clawteam team spawn-team my-team -d "Build the auth module" -n leader

# Spawn workers — each gets a git worktree + tmux window
clawteam spawn --team my-team --agent-name alice --task "Implement OAuth2 flow"
clawteam spawn --team my-team --agent-name bob   --task "Write unit tests for auth"

# Watch them work
clawteam board attach my-team
```

### 支援的智能體

| 智能體 | 啟動指令 | 狀態 |
|-------|--------------|--------|
| [OpenClaw](https://openclaw.ai) | `clawteam spawn tmux openclaw --team ...` | **預設** |
| [Claude Code](https://claude.ai/claude-code) | `clawteam spawn tmux claude --team ...` | 完整支援 |
| [Codex](https://openai.com/codex) | `clawteam spawn tmux codex --team ...` | 完整支援 |
| [nanobot](https://github.com/HKUDS/nanobot) | `clawteam spawn tmux nanobot --team ...` | 完整支援 |
| [Cursor](https://cursor.com) | `clawteam spawn subprocess cursor --team ...` | 實驗性 |
| 自訂腳本 | `clawteam spawn subprocess python --team ...` | 完整支援 |

---

## 安裝

### 第一步：前置條件

ClawTeam 需要 **Python 3.10+**、**tmux** 以及至少一個命令列程式碼智能體（OpenClaw、Claude Code、Codex 等）。

**檢查您已有的環境：**

```bash
python3 --version   # Need 3.10+
tmux -V             # Need any version
openclaw --version  # Or: claude --version / codex --version
```

**安裝缺少的前置條件：**

| 工具 | macOS | Ubuntu/Debian |
|------|-------|---------------|
| Python 3.10+ | `brew install python@3.12` | `sudo apt update && sudo apt install python3 python3-pip` |
| tmux | `brew install tmux` | `sudo apt install tmux` |
| OpenClaw | `pip install openclaw` | `pip install openclaw` |

> 如果使用 Claude Code 或 Codex 而非 OpenClaw，請按照它們各自的文件進行安裝。OpenClaw 是預設選項，但並非嚴格必需。

### 第二步：安裝 ClawTeam

> **⚠️ 請勿直接執行 `pip install clawteam` 或 `npm install -g clawteam`：**
> - `pip install clawteam` 會安裝 PyPI 上的上游版本，預設使用 `claude` 且缺少 OpenClaw 適配。
> - `npm install -g clawteam` 會安裝一個無關的搶注套件（發佈者 `a9logic`）。如果 `clawteam --version` 顯示 "Coming Soon"，表示裝錯了，請先 `npm uninstall -g clawteam`。
>
> **正確做法是下面三條命令——clone 之後的 `pip install -e .` 是必須的，它從本地倉庫安裝，不是從 PyPI。**

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
pip install -e .    # ← 必須執行！從本地倉庫安裝，不同於 pip install clawteam
```

可選 — P2P 傳輸層（ZeroMQ）：

```bash
pip install -e ".[p2p]"
```

### 第三步：建立 `~/bin/clawteam` 符號連結

被啟動的智能體在全新的 shell 環境中執行，可能沒有將 pip 的 bin 目錄加入 PATH。在 `~/bin` 中建立符號連結可確保 `clawteam` 始終可達：

```bash
mkdir -p ~/bin
ln -sf "$(which clawteam)" ~/bin/clawteam
```

如果 `which clawteam` 沒有回傳結果，請手動尋找二進位檔案：

```bash
# Common locations:
# ~/.local/bin/clawteam
# /opt/homebrew/bin/clawteam
# /usr/local/bin/clawteam
# /Library/Frameworks/Python.framework/Versions/3.*/bin/clawteam
find / -name clawteam -type f 2>/dev/null | head -5
```

然後確保 `~/bin` 在您的 PATH 中 — 如果尚未加入，請將以下內容新增至 `~/.zshrc` 或 `~/.bashrc`：

```bash
export PATH="$HOME/bin:$PATH"
```

### 第四步：安裝 OpenClaw 技能（僅限 OpenClaw 使用者）

技能檔案讓 OpenClaw 智能體能夠透過自然語言使用 ClawTeam。如果您不使用 OpenClaw，請跳過此步驟。

```bash
mkdir -p ~/.openclaw/workspace/skills/clawteam
cp skills/openclaw/SKILL.md ~/.openclaw/workspace/skills/clawteam/SKILL.md
```

### 第五步：配置執行授權（僅限 OpenClaw 使用者）

被啟動的 OpenClaw 智能體需要權限來執行 `clawteam` 指令。如果沒有配置，智能體會在互動式權限提示中被阻塞。

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

> 如果 `openclaw approvals` 失敗，OpenClaw 閘道器可能未在執行。請先啟動閘道器，然後重試。

### 第六步：驗證

```bash
clawteam --version          # Should print version
clawteam config health      # Should show all green
```

如果使用 OpenClaw，還需驗證技能是否已載入：

```bash
openclaw skills list | grep clawteam
```

### 自動化安裝腳本

上述第二至六步也可透過單一腳本完成：

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
bash scripts/install-openclaw.sh
```

### 疑難排解

| 問題 | 原因 | 解決方法 |
|---------|-------|-----|
| `clawteam: command not found` | pip 的 bin 目錄未在 PATH 中 | 執行第三步（符號連結 + PATH） |
| 被啟動的智能體找不到 `clawteam` | 智能體在沒有 pip PATH 的全新 shell 中執行 | 驗證 `~/bin/clawteam` 符號連結是否存在且 `~/bin` 已在 PATH 中 |
| `openclaw approvals` 失敗 | 閘道器未在執行 | 先啟動 `openclaw gateway`，然後重試第五步 |
| `exec-approvals.json not found` | OpenClaw 從未執行過 | 先執行一次 `openclaw` 以產生設定檔，然後重試第五步 |
| 智能體在權限提示中被阻塞 | 執行授權安全模式為 "full" | 執行第五步切換為 "allowlist" |
| `pip install -e .` 失敗 | 缺少建置依賴 | 先執行 `pip install hatchling` |
| `clawteam --version` 顯示 "Coming Soon" | 誤裝了 npm 同名搶注套件（`a9logic`，與本專案無關） | `npm uninstall -g clawteam`，然後按第二步重新安裝 |

---

## 使用案例

### 1. 自主機器學習研究 — 8 個智能體 x 8 張 GPU

基於 [@karpathy/autoresearch](https://github.com/karpathy/autoresearch)。一句提示詞即可在 H100 上啟動 8 個研究智能體，自主設計超過 2000 個實驗。

```
Human: "Use 8 GPUs to optimize train.py. Read program.md for instructions."

Leader agent:
├── Spawns 8 agents, each assigned a research direction (depth, width, LR, batch size...)
├── Each agent gets its own git worktree for isolated experiments
├── Every 30 min: checks results, cross-pollinates best configs to new agents
├── Reassigns GPUs as agents finish — fresh agents start from best known config
└── Result: val_bpb 1.044 → 0.977 (6.4% improvement) across 2430 experiments in ~30 GPU-hours
```

完整結果：[novix-science/autoresearch](https://github.com/novix-science/autoresearch)

### 2. 智能體驅動的軟體工程

```
Human: "Build a full-stack todo app with auth, database, and React frontend."

Leader agent:
├── Creates tasks with dependency chains (API schema → auth + DB → frontend → tests)
├── Spawns 5 agents (architect, 2 backend, frontend, tester) in separate worktrees
├── Dependencies auto-resolve: architect completes → backend unblocks → tester unblocks
├── Agents coordinate via inbox: "Here's the OpenAPI spec", "Auth endpoints ready"
└── Leader merges all worktrees into main when complete
```

### 3. 人工智慧對沖基金 — 模板啟動

一個 TOML 模板即可透過一條指令啟動完整的 7 智能體投資團隊：

```bash
clawteam launch hedge-fund --team fund1 --goal "Analyze AAPL, MSFT, NVDA for Q2 2026"
```

5 個分析師智能體（價值型、成長型、技術型、基本面、情緒面）並行工作。風險管理智能體綜合所有訊號。投資組合管理智能體做出最終決策。

模板是 TOML 檔案 — 您可以為任何領域**建立自己的模板**。

---

## 功能特性

<table>
<tr>
<td width="50%">

### 智能體自組織
- 領導者啟動並管理工作者
- 自動注入協調提示詞 — 零手動設定
- 工作者自行回報狀態和閒置狀態
- 任何命令列智能體皆可參與

### 工作區隔離
- 每個智能體擁有獨立的 **git worktree**
- 並行智能體之間不會產生合併衝突
- 支援檢查點、合併和清理指令
- 分支命名規則：`clawteam/{team}/{agent}`

### 含依賴關係的任務追蹤
- 共享看板：`pending` → `in_progress` → `completed` / `blocked`
- `--blocked-by` 依賴鏈，完成時自動解除阻塞
- `task wait` 阻塞等待直到所有任務完成

</td>
<td width="50%">

### 智能體間通訊
- 點對點收件匣（傳送、接收、預覽）
- 向所有團隊成員廣播
- 基於檔案（預設）或 ZeroMQ P2P 傳輸

### 監控與儀表板
- `board show` — 終端機看板
- `board live` — 自動重新整理儀表板
- `board attach` — 分割式 tmux 檢視所有智能體
- `board serve` — 即時更新的 Web 介面

### 團隊模板
- TOML 檔案定義團隊原型（角色、任務、提示詞）
- 一條指令：`clawteam launch <template>`
- 變數替換：`{goal}`、`{team_name}`、`{agent_name}`
- **按智能體分配模型**（預覽版）：為不同角色分配不同模型 — 詳見[下方](#按智能體分配模型預覽版)

</td>
</tr>
</table>

**更多功能：**計畫審批工作流、優雅的生命週期管理、所有指令支援 `--json` 輸出、跨機器支援（NFS/SSHFS 或 P2P）、多使用者命名空間、含自動回滾的啟動驗證、`fcntl` 檔案鎖確保並行安全。

---

## OpenClaw 整合

本分叉版本將 [OpenClaw](https://openclaw.ai) 設為**預設智能體**。沒有 ClawTeam 時，每個 OpenClaw 智能體各自孤立工作。ClawTeam 將其轉化為多智能體平台。

| 能力 | 單獨使用 OpenClaw | OpenClaw + ClawTeam |
|-----------|---------------|-------------------|
| **任務分配** | 手動逐一傳送訊息 | 領導者自主拆分、分配、監控 |
| **並行開發** | 共享工作目錄 | 每個智能體獨立的 git worktrees |
| **依賴關係** | 手動輪詢 | `--blocked-by` 自動解除阻塞 |
| **通訊方式** | 僅透過 AGI 中繼 | 直接點對點收件匣 + 廣播 |
| **可觀測性** | 閱讀日誌 | 看板 + 分割式 tmux 檢視 |

安裝技能後，即可在任何頻道與您的 OpenClaw 機器人對話：

| 您說的內容 | 發生的事情 |
|-------------|-------------|
| "建立一個 5 智能體團隊來開發 Web 應用程式" | 建立團隊、任務，在 tmux 中啟動 5 個智能體 |
| "啟動一個對沖基金分析團隊" | 執行 `clawteam launch hedge-fund`，啟動 7 個智能體 |
| "檢查我的智能體團隊狀態" | 執行 `clawteam board show` 顯示看板輸出 |

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

## 架構

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

所有狀態以 JSON 檔案形式儲存在 `~/.clawteam/` 中。無需資料庫，無需伺服器。透過 `fcntl` 檔案鎖的原子寫入確保當機安全。

| 設定項 | 環境變數 | 預設值 |
|---------|---------|---------|
| 資料目錄 | `CLAWTEAM_DATA_DIR` | `~/.clawteam` |
| 傳輸層 | `CLAWTEAM_TRANSPORT` | `file` |
| 工作區模式 | `CLAWTEAM_WORKSPACE` | `auto` |
| 啟動後端 | `CLAWTEAM_DEFAULT_BACKEND` | `tmux` |

---

## 指令參考

<details open>
<summary><strong>核心指令</strong></summary>

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
<summary><strong>工作區、計畫、生命週期、設定</strong></summary>

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

## 按智能體分配模型（預覽版）

> **分支：**[`feat/per-agent-model-assignment`](https://github.com/win4r/ClawTeam-OpenClaw/tree/feat/per-agent-model-assignment)
>
> 此功能可在獨立分支上進行早期測試。待配套的 OpenClaw `--model` 旗標正式發布後，將合併至 `main`。

為不同智能體角色分配不同模型，在多智能體集群中實現更佳的成本/效能權衡。

```bash
# Install from the feature branch
pip install -e "git+https://github.com/win4r/ClawTeam-OpenClaw.git@feat/per-agent-model-assignment#egg=clawteam"
```

**模板中的按智能體模型配置：**
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

**命令列旗標：**
```bash
clawteam spawn --model opus                          # single agent
clawteam launch my-template --model gpt-5.4          # override all agents
clawteam launch my-template --model-strategy auto     # auto-assign by role
```

詳見 [issue #1](https://github.com/win4r/ClawTeam-OpenClaw/issues/1) 的完整功能需求與討論。

---

## 發展路線

| 版本 | 內容 | 狀態 |
|---------|------|--------|
| v0.3 | 檔案 + P2P 傳輸、Web 介面、多使用者、模板 | 已發布 |
| v0.4 | Redis 傳輸 — 跨機器訊息傳遞 | 計畫中 |
| v0.5 | 共享狀態層 — 跨機器團隊設定 | 計畫中 |
| v0.6 | 智能體市場 — 社群模板 | 探索中 |
| v0.7 | 自適應排程 — 動態任務重新分配 | 探索中 |
| v1.0 | 生產等級 — 認證、權限、稽核日誌 | 探索中 |

---

## 參與貢獻

我們歡迎各類貢獻：

- **智能體整合** — 支援更多命令列智能體
- **團隊模板** — 面向新領域的 TOML 模板
- **傳輸後端** — Redis、NATS 等
- **儀表板改進** — Web 介面、Grafana
- **文件** — 教學與最佳實踐

---

## 致謝

- [@karpathy/autoresearch](https://github.com/karpathy/autoresearch) — 自主機器學習研究框架
- [OpenClaw](https://openclaw.ai) — 預設智能體後端
- [Claude Code](https://claude.ai/claude-code) 和 [Codex](https://openai.com/codex) — 支援的人工智慧程式碼智能體
- [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) — 對沖基金模板靈感來源
- [CLI-Anything](https://github.com/HKUDS/CLI-Anything) — 姊妹專案

## 授權條款

MIT — 可自由使用、修改與分發。

---

<div align="center">

**ClawTeam** — *智能體集群協作。*

</div>
