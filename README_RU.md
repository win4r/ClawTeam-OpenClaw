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
  <strong>Координация мультиагентного роя для CLI-агентов программирования — <a href="https://openclaw.ai">OpenClaw</a> по умолчанию</strong>
</p>

<p align="center">
  <a href="https://github.com/HKUDS/ClawTeam"><img src="https://img.shields.io/badge/upstream-HKUDS%2FClawTeam-purple?style=for-the-badge" alt="Upstream"></a>
  <a href="#-быстрый-старт"><img src="https://img.shields.io/badge/Quick_Start-3_min-blue?style=for-the-badge" alt="Quick Start"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/agents-OpenClaw_%7C_Claude_Code_%7C_Codex_%7C_nanobot-blueviolet" alt="Agents">
  <img src="https://img.shields.io/badge/transport-File_%7C_ZeroMQ_P2P-orange" alt="Transport">
  <img src="https://img.shields.io/badge/version-0.3.0-teal" alt="Version">
</p>

> **Форк [HKUDS/ClawTeam](https://github.com/HKUDS/ClawTeam)** с глубокой интеграцией OpenClaw: агент `openclaw` по умолчанию, изоляция сессий для каждого агента, автоматическая настройка разрешений на выполнение и бэкенды порождения агентов, готовые к продакшну. Все исправления из основного репозитория синхронизируются.

Вы ставите цель. Агентный рой делает всё остальное — порождает рабочих, разбивает задачи, координирует и объединяет результаты.

Работает с [OpenClaw](https://openclaw.ai) (по умолчанию), [Claude Code](https://claude.ai/claude-code), [Codex](https://openai.com/codex), [nanobot](https://github.com/HKUDS/nanobot), [Cursor](https://cursor.com) и любым CLI-агентом.

---

## Почему ClawTeam?

Современные ИИ-агенты мощны, но работают **изолированно**. ClawTeam позволяет агентам самоорганизовываться в команды — разделять работу, общаться и объединять результаты без ручного микроменеджмента.

| | ClawTeam | Другие мультиагентные фреймворки |
|---|---------|----------------------------|
| **Кто использует** | Сами ИИ-агенты | Люди, пишущие код оркестрации |
| **Настройка** | `pip install` + один промпт | Docker, облачные API, YAML-конфиги |
| **Инфраструктура** | Файловая система + tmux | Redis, очереди сообщений, базы данных |
| **Поддержка агентов** | Любой CLI-агент | Только специфичные для фреймворка |
| **Изоляция** | Git worktrees (реальные ветки) | Контейнеры или виртуальные окружения |

---

## Как это работает

<table>
<tr>
<td width="33%">

### Агенты порождают агентов
Лидер вызывает `clawteam spawn` для создания рабочих. Каждый получает свой **git worktree**, **окно tmux** и **идентичность**.

```bash
clawteam spawn --team my-team \
  --agent-name worker1 \
  --task "Implement auth module"
```

</td>
<td width="33%">

### Агенты общаются между собой
Рабочие проверяют входящие, обновляют задачи и сообщают результаты — всё через CLI-команды, **автоматически внедрённые** в их промпт.

```bash
clawteam task list my-team --owner me
clawteam inbox send my-team leader \
  "Auth done. All tests passing."
```

</td>
<td width="33%">

### Вы просто наблюдаете
Отслеживайте рой через мозаичное представление tmux или веб-интерфейс. Лидер занимается координацией.

```bash
clawteam board attach my-team
# Or web dashboard
clawteam board serve --port 8080
```

</td>
</tr>
</table>

---

## Быстрый старт

### Вариант 1: Пусть агент ведёт (Рекомендуется)

Установите ClawTeam, затем дайте промпт вашему агенту:

```
"Build a web app. Use clawteam to split the work across multiple agents."
```

Агент автоматически создаёт команду, порождает рабочих, назначает задачи и координирует — всё через CLI `clawteam`.

### Вариант 2: Управляйте вручную

```bash
# Create a team
clawteam team spawn-team my-team -d "Build the auth module" -n leader

# Spawn workers — each gets a git worktree + tmux window
clawteam spawn --team my-team --agent-name alice --task "Implement OAuth2 flow"
clawteam spawn --team my-team --agent-name bob   --task "Write unit tests for auth"

# Watch them work
clawteam board attach my-team
```

### Поддерживаемые агенты

| Агент | Команда порождения | Статус |
|-------|--------------|--------|
| [OpenClaw](https://openclaw.ai) | `clawteam spawn tmux openclaw --team ...` | **По умолчанию** |
| [Claude Code](https://claude.ai/claude-code) | `clawteam spawn tmux claude --team ...` | Полная поддержка |
| [Codex](https://openai.com/codex) | `clawteam spawn tmux codex --team ...` | Полная поддержка |
| [nanobot](https://github.com/HKUDS/nanobot) | `clawteam spawn tmux nanobot --team ...` | Полная поддержка |
| [Cursor](https://cursor.com) | `clawteam spawn subprocess cursor --team ...` | Экспериментально |
| Пользовательские скрипты | `clawteam spawn subprocess python --team ...` | Полная поддержка |

---

## Установка

### Шаг 1: Предварительные требования

ClawTeam требует **Python 3.10+**, **tmux** и хотя бы один CLI-агент для программирования (OpenClaw, Claude Code, Codex и т.д.).

**Проверьте, что у вас уже установлено:**

```bash
python3 --version   # Need 3.10+
tmux -V             # Need any version
openclaw --version  # Or: claude --version / codex --version
```

**Установите недостающие компоненты:**

| Инструмент | macOS | Ubuntu/Debian |
|------|-------|---------------|
| Python 3.10+ | `brew install python@3.12` | `sudo apt update && sudo apt install python3 python3-pip` |
| tmux | `brew install tmux` | `sudo apt install tmux` |
| OpenClaw | `pip install openclaw` | `pip install openclaw` |

> Если вы используете Claude Code или Codex вместо OpenClaw, установите их согласно их документации. OpenClaw используется по умолчанию, но не является строго обязательным.

### Шаг 2: Установка ClawTeam

> **⚠️ НЕ выполняйте `pip install clawteam` или `npm install -g clawteam` напрямую:**
> - `pip install clawteam` установит версию из основного репозитория PyPI, которая по умолчанию использует `claude` и не содержит адаптаций для OpenClaw.
> - `npm install -g clawteam` установит постороннюю пакет-сквоттер (издатель `a9logic`). Если `clawteam --version` показывает "Coming Soon", установлен неправильный пакет. Сначала выполните `npm uninstall -g clawteam`.
>
> **Используйте три команды ниже — `pip install -e .` после клонирования обязателен. Он устанавливает из локального репозитория, а не из PyPI.**

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
pip install -e .    # ← Обязательно! Установка из локального репозитория, НЕ то же самое что pip install clawteam
```

Опционально — P2P-транспорт (ZeroMQ):

```bash
pip install -e ".[p2p]"
```

### Шаг 3: Создание символической ссылки `~/bin/clawteam`

Порождённые агенты запускаются в чистых оболочках, которые могут не иметь директорию pip в PATH. Символическая ссылка в `~/bin` гарантирует, что `clawteam` всегда доступен:

```bash
mkdir -p ~/bin
ln -sf "$(which clawteam)" ~/bin/clawteam
```

Если `which clawteam` ничего не возвращает, найдите бинарный файл вручную:

```bash
# Common locations:
# ~/.local/bin/clawteam
# /opt/homebrew/bin/clawteam
# /usr/local/bin/clawteam
# /Library/Frameworks/Python.framework/Versions/3.*/bin/clawteam
find / -name clawteam -type f 2>/dev/null | head -5
```

Затем убедитесь, что `~/bin` включён в PATH — добавьте следующее в `~/.zshrc` или `~/.bashrc`, если ещё не добавлено:

```bash
export PATH="$HOME/bin:$PATH"
```

### Шаг 4: Установка навыка OpenClaw (только для пользователей OpenClaw)

Файл навыка обучает агентов OpenClaw работе с ClawTeam через естественный язык. Пропустите этот шаг, если вы не используете OpenClaw.

```bash
mkdir -p ~/.openclaw/workspace/skills/clawteam
cp skills/openclaw/SKILL.md ~/.openclaw/workspace/skills/clawteam/SKILL.md
```

### Шаг 5: Настройка разрешений на выполнение (только для пользователей OpenClaw)

Порождённым агентам OpenClaw требуется разрешение на выполнение команд `clawteam`. Без этого агенты будут блокироваться на интерактивных запросах разрешений.

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

> Если `openclaw approvals` не работает, шлюз OpenClaw может быть не запущен. Сначала запустите его, затем повторите попытку.

### Шаг 6: Проверка

```bash
clawteam --version          # Should print version
clawteam config health      # Should show all green
```

Если вы используете OpenClaw, также проверьте, что навык загружен:

```bash
openclaw skills list | grep clawteam
```

### Автоматический установщик

Шаги 2–6, описанные выше, также доступны в виде единого скрипта:

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
bash scripts/install-openclaw.sh
```

### Устранение неполадок

| Проблема | Причина | Решение |
|---------|-------|-----|
| `clawteam: command not found` | Директория pip не в PATH | Выполните Шаг 3 (символическая ссылка + PATH) |
| Порождённые агенты не находят `clawteam` | Агенты запускаются в чистых оболочках без PATH pip | Убедитесь, что символическая ссылка `~/bin/clawteam` существует и `~/bin` в PATH |
| `openclaw approvals` не работает | Шлюз не запущен | Сначала запустите `openclaw gateway`, затем повторите Шаг 5 |
| `exec-approvals.json not found` | OpenClaw ни разу не запускался | Запустите `openclaw` один раз для генерации конфигурации, затем повторите Шаг 5 |
| Агенты блокируются на запросах разрешений | Режим безопасности exec approvals — "full" | Выполните Шаг 5 для переключения на "allowlist" |
| `pip install -e .` не работает | Отсутствуют зависимости сборки | Сначала выполните `pip install hatchling` |
| `clawteam --version` показывает "Coming Soon" | Установлен npm-пакет-сквоттер (`a9logic`, не связан с этим проектом) | `npm uninstall -g clawteam`, затем переустановить по шагу 2 |

---

## Примеры использования

### 1. Автономное исследование в области МО — 8 агентов x 8 GPU

На основе [@karpathy/autoresearch](https://github.com/karpathy/autoresearch). Один промпт запускает 8 исследовательских агентов на H100, которые автономно проектируют 2000+ экспериментов.

```
Human: "Use 8 GPUs to optimize train.py. Read program.md for instructions."

Leader agent:
├── Spawns 8 agents, each assigned a research direction (depth, width, LR, batch size...)
├── Each agent gets its own git worktree for isolated experiments
├── Every 30 min: checks results, cross-pollinates best configs to new agents
├── Reassigns GPUs as agents finish — fresh agents start from best known config
└── Result: val_bpb 1.044 → 0.977 (6.4% improvement) across 2430 experiments in ~30 GPU-hours
```

Полные результаты: [novix-science/autoresearch](https://github.com/novix-science/autoresearch)

### 2. Агентная разработка программного обеспечения

```
Human: "Build a full-stack todo app with auth, database, and React frontend."

Leader agent:
├── Creates tasks with dependency chains (API schema → auth + DB → frontend → tests)
├── Spawns 5 agents (architect, 2 backend, frontend, tester) in separate worktrees
├── Dependencies auto-resolve: architect completes → backend unblocks → tester unblocks
├── Agents coordinate via inbox: "Here's the OpenAPI spec", "Auth endpoints ready"
└── Leader merges all worktrees into main when complete
```

### 3. ИИ-хедж-фонд — запуск из шаблона

TOML-шаблон порождает полноценную инвестиционную команду из 7 агентов одной командой:

```bash
clawteam launch hedge-fund --team fund1 --goal "Analyze AAPL, MSFT, NVDA for Q2 2026"
```

5 агентов-аналитиков (стоимость, рост, технический анализ, фундаментальный анализ, настроения рынка) работают параллельно. Риск-менеджер синтезирует все сигналы. Портфельный управляющий принимает итоговые решения.

Шаблоны — это файлы TOML. **Создавайте собственные** для любой предметной области.

---

## Возможности

<table>
<tr>
<td width="50%">

### Самоорганизация агентов
- Лидер порождает рабочих и управляет ими
- Автоматически внедряемый промпт координации — нулевая ручная настройка
- Рабочие самостоятельно сообщают статус и состояние простоя
- Любой CLI-агент может участвовать

### Изоляция рабочих пространств
- Каждый агент получает свой **git worktree**
- Никаких конфликтов слияния между параллельными агентами
- Команды для создания контрольных точек, слияния и очистки
- Именование веток: `clawteam/{team}/{agent}`

### Отслеживание задач с зависимостями
- Общая канбан-доска: `pending` → `in_progress` → `completed` / `blocked`
- Цепочки `--blocked-by` с автоматической разблокировкой при завершении
- `task wait` блокирует выполнение до завершения всех задач

</td>
<td width="50%">

### Межагентный обмен сообщениями
- Двусторонние входящие (отправка, получение, просмотр)
- Широковещательная рассылка всем участникам команды
- Файловый транспорт (по умолчанию) или ZeroMQ P2P

### Мониторинг и панели управления
- `board show` — канбан-доска в терминале
- `board live` — автообновляемая панель
- `board attach` — мозаичное представление всех агентов в tmux
- `board serve` — веб-интерфейс с обновлениями в реальном времени

### Шаблоны команд
- TOML-файлы определяют архетипы команд (роли, задачи, промпты)
- Одна команда: `clawteam launch <template>`
- Подстановка переменных: `{goal}`, `{team_name}`, `{agent_name}`
- **Назначение модели для каждого агента** (предварительная версия): назначайте разные модели разным ролям — см. [ниже](#назначение-модели-для-каждого-агента-предварительная-версия)

</td>
</tr>
</table>

**Также:** рабочие процессы утверждения планов, корректное управление жизненным циклом, вывод `--json` для всех команд, поддержка нескольких машин (NFS/SSHFS или P2P), многопользовательские пространства имён, валидация порождения с автоматическим откатом, блокировка файлов `fcntl` для безопасности при конкурентном доступе.

---

## Интеграция с OpenClaw

Этот форк делает [OpenClaw](https://openclaw.ai) **агентом по умолчанию**. Без ClawTeam каждый агент OpenClaw работает изолированно. ClawTeam превращает его в мультиагентную платформу.

| Возможность | OpenClaw в одиночку | OpenClaw + ClawTeam |
|-----------|---------------|-------------------|
| **Назначение задач** | Ручная отправка сообщений каждому агенту | Лидер автономно разбивает, назначает, отслеживает |
| **Параллельная разработка** | Общая рабочая директория | Изолированные git worktrees для каждого агента |
| **Зависимости** | Ручной опрос | `--blocked-by` с автоматической разблокировкой |
| **Коммуникация** | Только через ретранслятор AGI | Прямые двусторонние входящие + широковещание |
| **Наблюдаемость** | Чтение логов | Канбан-доска + мозаичное представление tmux |

После установки навыка общайтесь с вашим ботом OpenClaw в любом канале:

| Что вы говорите | Что происходит |
|-------------|-------------|
| "Создай команду из 5 агентов для создания веб-приложения" | Создаётся команда, задачи, порождаются 5 агентов в tmux |
| "Запусти аналитическую команду хедж-фонда" | `clawteam launch hedge-fund` с 7 агентами |
| "Покажи статус моей команды агентов" | `clawteam board show` с выводом канбан-доски |

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

## Архитектура

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

Всё состояние хранится в `~/.clawteam/` в виде файлов JSON. Без базы данных, без сервера. Атомарная запись с файловой блокировкой `fcntl` обеспечивает устойчивость к сбоям.

| Параметр | Переменная окружения | По умолчанию |
|---------|---------|---------|
| Директория данных | `CLAWTEAM_DATA_DIR` | `~/.clawteam` |
| Транспорт | `CLAWTEAM_TRANSPORT` | `file` |
| Режим рабочего пространства | `CLAWTEAM_WORKSPACE` | `auto` |
| Бэкенд порождения | `CLAWTEAM_DEFAULT_BACKEND` | `tmux` |

---

## Справочник команд

<details open>
<summary><strong>Основные команды</strong></summary>

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
<summary><strong>Рабочее пространство, план, жизненный цикл, конфигурация</strong></summary>

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

## Назначение модели для каждого агента (Предварительная версия)

> **Ветка:** [`feat/per-agent-model-assignment`](https://github.com/win4r/ClawTeam-OpenClaw/tree/feat/per-agent-model-assignment)
>
> Эта функция доступна для раннего тестирования в отдельной ветке. Она будет объединена в `main` после выхода соответствующего флага `--model` в OpenClaw.

Назначайте разные модели разным ролям агентов для оптимального баланса стоимости и производительности в мультиагентных роях.

```bash
# Install from the feature branch
pip install -e "git+https://github.com/win4r/ClawTeam-OpenClaw.git@feat/per-agent-model-assignment#egg=clawteam"
```

**Назначение модели в шаблонах:**
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

**Флаги CLI:**
```bash
clawteam spawn --model opus                          # single agent
clawteam launch my-template --model gpt-5.4          # override all agents
clawteam launch my-template --model-strategy auto     # auto-assign by role
```

Подробности см. в [issue #1](https://github.com/win4r/ClawTeam-OpenClaw/issues/1) — полное описание функции и обсуждение.

---

## Дорожная карта

| Версия | Что | Статус |
|---------|------|--------|
| v0.3 | Файловый и P2P-транспорт, веб-интерфейс, многопользовательский режим, шаблоны | Выпущено |
| v0.4 | Redis-транспорт — обмен сообщениями между машинами | Запланировано |
| v0.5 | Уровень общего состояния — конфигурация команды на нескольких машинах | Запланировано |
| v0.6 | Маркетплейс агентов — шаблоны от сообщества | Исследуется |
| v0.7 | Адаптивное планирование — динамическое перераспределение задач | Исследуется |
| v1.0 | Продакшн-уровень — аутентификация, права доступа, журналы аудита | Исследуется |

---

## Участие в разработке

Мы приветствуем вклад в проект:

- **Интеграции с агентами** — поддержка большего числа CLI-агентов
- **Шаблоны команд** — TOML-шаблоны для новых предметных областей
- **Транспортные бэкенды** — Redis, NATS и др.
- **Улучшения панели управления** — веб-интерфейс, Grafana
- **Документация** — руководства и лучшие практики

---

## Благодарности

- [@karpathy/autoresearch](https://github.com/karpathy/autoresearch) — фреймворк для автономных исследований в области МО
- [OpenClaw](https://openclaw.ai) — бэкенд агента по умолчанию
- [Claude Code](https://claude.ai/claude-code) и [Codex](https://openai.com/codex) — поддерживаемые ИИ-агенты для программирования
- [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) — вдохновение для шаблона хедж-фонда
- [CLI-Anything](https://github.com/HKUDS/CLI-Anything) — родственный проект

## Лицензия

MIT — свободное использование, модификация и распространение.

---

<div align="center">

**ClawTeam** — *Интеллект агентного роя.*

</div>
