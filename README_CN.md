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
  <strong>面向命令行编程智能体的多智能体集群协调框架 — 默认使用 <a href="https://openclaw.ai">OpenClaw</a></strong>
</p>

<p align="center">
  <a href="https://github.com/HKUDS/ClawTeam"><img src="https://img.shields.io/badge/upstream-HKUDS%2FClawTeam-purple?style=for-the-badge" alt="Upstream"></a>
  <a href="#-快速开始"><img src="https://img.shields.io/badge/Quick_Start-3_min-blue?style=for-the-badge" alt="Quick Start"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/agents-OpenClaw_%7C_Claude_Code_%7C_Codex_%7C_nanobot-blueviolet" alt="Agents">
  <img src="https://img.shields.io/badge/transport-File_%7C_ZeroMQ_P2P-orange" alt="Transport">
  <img src="https://img.shields.io/badge/version-0.3.0-teal" alt="Version">
</p>

> **[HKUDS/ClawTeam](https://github.com/HKUDS/ClawTeam) 的 Fork 版本**，深度集成 OpenClaw：默认使用 `openclaw` 智能体、每个智能体独立会话隔离、执行审批自动配置，以及生产级加固的进程生成后端。所有上游修复均已同步。

你只需设定目标。智能体集群会处理其余一切——生成工作节点、拆分任务、协调合作、合并结果。

支持 [OpenClaw](https://openclaw.ai)（默认）、[Claude Code](https://claude.ai/claude-code)、[Codex](https://openai.com/codex)、[nanobot](https://github.com/HKUDS/nanobot)、[Cursor](https://cursor.com) 及任何命令行智能体。

---

## 为什么选择 ClawTeam？

当前的 AI 智能体虽然强大，但都在**孤立地**工作。ClawTeam 让智能体能够自组织成团队——拆分工作、相互通信、协同汇聚结果，无需人工微管理。

| | ClawTeam | 其他多智能体框架 |
|---|---------|----------------------------|
| **使用者** | AI 智能体自身 | 编写编排代码的人类 |
| **部署方式** | `pip install` + 一句提示词 | Docker、云 API、YAML 配置 |
| **基础设施** | 文件系统 + tmux | Redis、消息队列、数据库 |
| **智能体支持** | 任何命令行智能体 | 仅支持特定框架 |
| **隔离方式** | Git worktrees（真实分支） | 容器或虚拟环境 |

---

## 工作原理

<table>
<tr>
<td width="33%">

### 智能体生成智能体
领导者调用 `clawteam spawn` 创建工作节点。每个节点拥有独立的 **Git worktree**、**tmux 窗口**和**身份标识**。

```bash
clawteam spawn --team my-team \
  --agent-name worker1 \
  --task "Implement auth module"
```

</td>
<td width="33%">

### 智能体之间直接通信
工作节点检查收件箱、更新任务、汇报结果——所有操作通过**自动注入**到提示词中的命令行指令完成。

```bash
clawteam task list my-team --owner me
clawteam inbox send my-team leader \
  "Auth done. All tests passing."
```

</td>
<td width="33%">

### 你只需观察
通过平铺的 tmux 视图或 Web 界面监控集群。领导者负责协调一切。

```bash
clawteam board attach my-team
# Or web dashboard
clawteam board serve --port 8080
```

</td>
</tr>
</table>

---

## 快速开始

### 方式一：让智能体自主驱动（推荐）

安装 ClawTeam，然后向你的智能体发出提示：

```
"Build a web app. Use clawteam to split the work across multiple agents."
```

智能体会自动创建团队、生成工作节点、分配任务并协调——全部通过 `clawteam` 命令行完成。

### 方式二：手动驱动

```bash
# Create a team
clawteam team spawn-team my-team -d "Build the auth module" -n leader

# Spawn workers — each gets a git worktree + tmux window
clawteam spawn --team my-team --agent-name alice --task "Implement OAuth2 flow"
clawteam spawn --team my-team --agent-name bob   --task "Write unit tests for auth"

# Watch them work
clawteam board attach my-team
```

### 支持的智能体

| 智能体 | 生成命令 | 状态 |
|-------|--------------|--------|
| [OpenClaw](https://openclaw.ai) | `clawteam spawn tmux openclaw --team ...` | **默认** |
| [Claude Code](https://claude.ai/claude-code) | `clawteam spawn tmux claude --team ...` | 完整支持 |
| [Codex](https://openai.com/codex) | `clawteam spawn tmux codex --team ...` | 完整支持 |
| [nanobot](https://github.com/HKUDS/nanobot) | `clawteam spawn tmux nanobot --team ...` | 完整支持 |
| [Cursor](https://cursor.com) | `clawteam spawn subprocess cursor --team ...` | 实验性支持 |
| 自定义脚本 | `clawteam spawn subprocess python --team ...` | 完整支持 |

---

## 安装

### 第一步：前置条件

ClawTeam 需要 **Python 3.10+**、**tmux** 以及至少一个命令行编程智能体（OpenClaw、Claude Code、Codex 等）。

**检查已有工具：**

```bash
python3 --version   # Need 3.10+
tmux -V             # Need any version
openclaw --version  # Or: claude --version / codex --version
```

**安装缺失的前置工具：**

| 工具 | macOS | Ubuntu/Debian |
|------|-------|---------------|
| Python 3.10+ | `brew install python@3.12` | `sudo apt update && sudo apt install python3 python3-pip` |
| tmux | `brew install tmux` | `sudo apt install tmux` |
| OpenClaw | `pip install openclaw` | `pip install openclaw` |

> 如果使用 Claude Code 或 Codex 替代 OpenClaw，请按照其各自的文档安装。OpenClaw 是默认选项，但并非强制要求。

### 第二步：安装 ClawTeam

> **⚠️ 请勿直接运行 `pip install clawteam` 或 `npm install -g clawteam`：**
> - `pip install clawteam` 会安装 PyPI 上的上游版本，默认使用 `claude` 且缺少 OpenClaw 适配。
> - `npm install -g clawteam` 会安装一个无关的抢注包（发布者 `a9logic`）。如果 `clawteam --version` 显示 "Coming Soon"，说明装错了，请先 `npm uninstall -g clawteam`。
>
> **正确做法是下面三条命令——clone 之后的 `pip install -e .` 是必须的，它从本地仓库安装，不是从 PyPI。**

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
pip install -e .    # ← 必须执行！从本地仓库安装，不同于 pip install clawteam
```

可选——P2P 传输（ZeroMQ）：

```bash
pip install -e ".[p2p]"
```

### 第三步：创建 `~/bin/clawteam` 软链接

生成的智能体在全新的 shell 环境中运行，PATH 中可能没有 pip 的 bin 目录。在 `~/bin` 下创建软链接可确保 `clawteam` 命令始终可用：

```bash
mkdir -p ~/bin
ln -sf "$(which clawteam)" ~/bin/clawteam
```

如果 `which clawteam` 没有返回结果，手动查找二进制文件：

```bash
# Common locations:
# ~/.local/bin/clawteam
# /opt/homebrew/bin/clawteam
# /usr/local/bin/clawteam
# /Library/Frameworks/Python.framework/Versions/3.*/bin/clawteam
find / -name clawteam -type f 2>/dev/null | head -5
```

然后确保 `~/bin` 在你的 PATH 中——如果尚未添加，将以下内容加入 `~/.zshrc` 或 `~/.bashrc`：

```bash
export PATH="$HOME/bin:$PATH"
```

### 第四步：安装 OpenClaw 技能（仅 OpenClaw 用户）

技能文件教会 OpenClaw 智能体如何通过自然语言使用 ClawTeam。如果你不使用 OpenClaw，可跳过此步骤。

```bash
mkdir -p ~/.openclaw/workspace/skills/clawteam
cp skills/openclaw/SKILL.md ~/.openclaw/workspace/skills/clawteam/SKILL.md
```

### 第五步：配置执行审批（仅 OpenClaw 用户）

生成的 OpenClaw 智能体需要权限才能运行 `clawteam` 命令。如果不配置，智能体会在交互式权限提示处阻塞。

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

> 如果 `openclaw approvals` 失败，可能是 OpenClaw 网关未运行。请先启动网关，然后重试。

### 第六步：验证

```bash
clawteam --version          # Should print version
clawteam config health      # Should show all green
```

如果使用 OpenClaw，还需验证技能是否已加载：

```bash
openclaw skills list | grep clawteam
```

### 自动化安装脚本

上述第 2-6 步也可通过一个脚本完成：

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
bash scripts/install-openclaw.sh
```

### 故障排查

| 问题 | 原因 | 解决方法 |
|---------|-------|-----|
| `clawteam: command not found` | pip 的 bin 目录不在 PATH 中 | 执行第三步（软链接 + PATH） |
| 生成的智能体找不到 `clawteam` | 智能体在没有 pip PATH 的全新 shell 中运行 | 确认 `~/bin/clawteam` 软链接存在且 `~/bin` 在 PATH 中 |
| `openclaw approvals` 失败 | 网关未运行 | 先启动 `openclaw gateway`，再重试第五步 |
| `exec-approvals.json not found` | OpenClaw 从未运行过 | 先运行一次 `openclaw` 生成配置文件，再重试第五步 |
| 智能体在权限提示处阻塞 | 执行审批安全模式为 "full" | 执行第五步切换为 "allowlist" |
| `pip install -e .` 失败 | 缺少构建依赖 | 先运行 `pip install hatchling` |
| `clawteam --version` 显示 "Coming Soon" | 误装了 npm 同名抢注包（`a9logic`，与本项目无关） | `npm uninstall -g clawteam`，然后按第二步重新安装 |

---

## 应用场景

### 1. 自主机器学习研究 — 8 个智能体 x 8 块 GPU

基于 [@karpathy/autoresearch](https://github.com/karpathy/autoresearch)。一句提示词启动 8 个研究智能体，跨 H100 GPU 自主设计 2000 多个实验。

```
Human: "Use 8 GPUs to optimize train.py. Read program.md for instructions."

Leader agent:
├── Spawns 8 agents, each assigned a research direction (depth, width, LR, batch size...)
├── Each agent gets its own git worktree for isolated experiments
├── Every 30 min: checks results, cross-pollinates best configs to new agents
├── Reassigns GPUs as agents finish — fresh agents start from best known config
└── Result: val_bpb 1.044 → 0.977 (6.4% improvement) across 2430 experiments in ~30 GPU-hours
```

完整结果：[novix-science/autoresearch](https://github.com/novix-science/autoresearch)

### 2. 智能体驱动的软件工程

```
Human: "Build a full-stack todo app with auth, database, and React frontend."

Leader agent:
├── Creates tasks with dependency chains (API schema → auth + DB → frontend → tests)
├── Spawns 5 agents (architect, 2 backend, frontend, tester) in separate worktrees
├── Dependencies auto-resolve: architect completes → backend unblocks → tester unblocks
├── Agents coordinate via inbox: "Here's the OpenAPI spec", "Auth endpoints ready"
└── Leader merges all worktrees into main when complete
```

### 3. AI 对冲基金 — 模板一键启动

一个 TOML 模板通过一条命令生成完整的 7 智能体投资团队：

```bash
clawteam launch hedge-fund --team fund1 --goal "Analyze AAPL, MSFT, NVDA for Q2 2026"
```

5 个分析师智能体（价值分析、成长分析、技术分析、基本面分析、情绪分析）并行工作。风险管理者综合所有信号。投资组合经理做出最终决策。

模板是 TOML 文件——**可以为任何领域创建自定义模板**。

---

## 功能特性

<table>
<tr>
<td width="50%">

### 智能体自组织
- 领导者生成并管理工作节点
- 自动注入协调提示词——零手动配置
- 工作节点自行上报状态和空闲信息
- 任何命令行智能体均可参与

### 工作区隔离
- 每个智能体拥有独立的 **Git worktree**
- 并行智能体之间不会产生合并冲突
- 支持检查点、合并和清理命令
- 分支命名：`clawteam/{team}/{agent}`

### 带依赖关系的任务追踪
- 共享看板：`pending` → `in_progress` → `completed` / `blocked`
- `--blocked-by` 链式依赖，任务完成时自动解除阻塞
- `task wait` 阻塞等待直到所有任务完成

</td>
<td width="50%">

### 智能体间消息通信
- 点对点收件箱（发送、接收、预览）
- 向所有团队成员广播
- 基于文件（默认）或 ZeroMQ P2P 传输

### 监控与仪表盘
- `board show` — 终端看板
- `board live` — 自动刷新仪表盘
- `board attach` — 平铺 tmux 视图查看所有智能体
- `board serve` — 实时更新的 Web 界面

### 团队模板
- TOML 文件定义团队原型（角色、任务、提示词）
- 一条命令：`clawteam launch <template>`
- 变量替换：`{goal}`、`{team_name}`、`{agent_name}`
- **每智能体模型分配**（预览版）：为不同角色分配不同模型——参见[下文](#每智能体模型分配预览版)

</td>
</tr>
</table>

**其他特性：** 计划审批工作流、优雅的生命周期管理、所有命令支持 `--json` 输出、跨机器支持（NFS/SSHFS 或 P2P）、多用户命名空间、带自动回滚的生成校验、基于 `fcntl` 文件锁的并发安全保障。

---

## OpenClaw 集成

本 Fork 版本将 [OpenClaw](https://openclaw.ai) 设为**默认智能体**。没有 ClawTeam 时，每个 OpenClaw 智能体各自独立工作。ClawTeam 将其转变为多智能体平台。

| 能力 | 单独使用 OpenClaw | OpenClaw + ClawTeam |
|-----------|---------------|-------------------|
| **任务分配** | 手动向每个智能体发消息 | 领导者自主拆分、分配、监控 |
| **并行开发** | 共享工作目录 | 每个智能体独立的 Git worktree |
| **依赖管理** | 手动轮询 | `--blocked-by` 自动解除阻塞 |
| **通信方式** | 仅通过 AGI 中继 | 直接的点对点收件箱 + 广播 |
| **可观测性** | 查看日志 | 看板 + 平铺 tmux 视图 |

安装技能后，在任何频道与你的 OpenClaw 机器人对话：

| 你说的话 | 发生的事情 |
|-------------|-------------|
| "创建一个 5 智能体团队来构建 Web 应用" | 创建团队、任务，在 tmux 中生成 5 个智能体 |
| "启动一个对冲基金分析团队" | 执行 `clawteam launch hedge-fund`，启动 7 个智能体 |
| "查看我的智能体团队状态" | 执行 `clawteam board show`，输出看板 |

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

## 架构

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

所有状态以 JSON 文件形式存储在 `~/.clawteam/` 中。无需数据库，无需服务器。通过 `fcntl` 文件锁进行原子写入以确保崩溃安全。

| 配置项 | 环境变量 | 默认值 |
|---------|---------|---------|
| 数据目录 | `CLAWTEAM_DATA_DIR` | `~/.clawteam` |
| 传输方式 | `CLAWTEAM_TRANSPORT` | `file` |
| 工作区模式 | `CLAWTEAM_WORKSPACE` | `auto` |
| 生成后端 | `CLAWTEAM_DEFAULT_BACKEND` | `tmux` |

---

## 命令参考

<details open>
<summary><strong>核心命令</strong></summary>

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
<summary><strong>工作区、计划、生命周期、配置</strong></summary>

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

## 每智能体模型分配（预览版）

> **分支：** [`feat/per-agent-model-assignment`](https://github.com/win4r/ClawTeam-OpenClaw/tree/feat/per-agent-model-assignment)
>
> 此功能在单独分支上提供早期测试。待 OpenClaw 配套的 `--model` 参数发布后，将合并到 `main` 分支。

为不同智能体角色分配不同模型，以在多智能体集群中实现更优的成本/性能平衡。

```bash
# Install from the feature branch
pip install -e "git+https://github.com/win4r/ClawTeam-OpenClaw.git@feat/per-agent-model-assignment#egg=clawteam"
```

**模板中的每智能体模型配置：**
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

**命令行参数：**
```bash
clawteam spawn --model opus                          # single agent
clawteam launch my-template --model gpt-5.4          # override all agents
clawteam launch my-template --model-strategy auto     # auto-assign by role
```

参见 [issue #1](https://github.com/win4r/ClawTeam-OpenClaw/issues/1) 了解完整的功能需求和讨论。

---

## 路线图

| 版本 | 内容 | 状态 |
|---------|------|--------|
| v0.3 | 文件 + P2P 传输、Web 界面、多用户、模板 | 已发布 |
| v0.4 | Redis 传输——跨机器消息通信 | 计划中 |
| v0.5 | 共享状态层——跨机器团队配置 | 计划中 |
| v0.6 | 智能体市场——社区模板 | 探索中 |
| v0.7 | 自适应调度——动态任务重分配 | 探索中 |
| v1.0 | 生产级——认证、权限、审计日志 | 探索中 |

---

## 贡献

欢迎贡献：

- **智能体集成** — 支持更多命令行智能体
- **团队模板** — 面向新领域的 TOML 模板
- **传输后端** — Redis、NATS 等
- **仪表盘改进** — Web 界面、Grafana
- **文档** — 教程和最佳实践

---

## 致谢

- [@karpathy/autoresearch](https://github.com/karpathy/autoresearch) — 自主机器学习研究框架
- [OpenClaw](https://openclaw.ai) — 默认智能体后端
- [Claude Code](https://claude.ai/claude-code) 和 [Codex](https://openai.com/codex) — 支持的 AI 编程智能体
- [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) — 对冲基金模板的灵感来源
- [CLI-Anything](https://github.com/HKUDS/CLI-Anything) — 姊妹项目

## 许可证

MIT — 可自由使用、修改和分发。

---

<div align="center">

**ClawTeam** — *智能体集群协作。*

</div>
