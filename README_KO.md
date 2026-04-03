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
  <strong>CLI 코딩 에이전트를 위한 멀티 에이전트 스웜 협업 — <a href="https://openclaw.ai">OpenClaw</a> 기본 탑재</strong>
</p>

<p align="center">
  <a href="https://github.com/HKUDS/ClawTeam"><img src="https://img.shields.io/badge/upstream-HKUDS%2FClawTeam-purple?style=for-the-badge" alt="Upstream"></a>
  <a href="#-빠른-시작"><img src="https://img.shields.io/badge/Quick_Start-3_min-blue?style=for-the-badge" alt="Quick Start"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/agents-OpenClaw_%7C_Claude_Code_%7C_Codex_%7C_nanobot-blueviolet" alt="Agents">
  <img src="https://img.shields.io/badge/transport-File_%7C_ZeroMQ_P2P-orange" alt="Transport">
  <img src="https://img.shields.io/badge/version-0.3.0-teal" alt="Version">
</p>

> **[HKUDS/ClawTeam](https://github.com/HKUDS/ClawTeam)의 포크**로, OpenClaw과의 심층 통합을 제공합니다: 기본 `openclaw` 에이전트, 에이전트별 세션 격리, 실행 승인 자동 구성, 프로덕션 수준의 스폰 백엔드. 모든 업스트림 수정 사항이 동기화됩니다.

목표를 설정하세요. 에이전트 스웜이 나머지를 처리합니다 — 워커 생성, 작업 분할, 조율, 결과 병합까지 모두 자동으로.

[OpenClaw](https://openclaw.ai) (기본), [Claude Code](https://claude.ai/claude-code), [Codex](https://openai.com/codex), [nanobot](https://github.com/HKUDS/nanobot), [Cursor](https://cursor.com) 및 모든 CLI 에이전트와 호환됩니다.

---

## 왜 ClawTeam인가?

현재 AI 에이전트는 강력하지만 **독립적으로** 작동합니다. ClawTeam은 에이전트들이 스스로 팀을 구성할 수 있게 해줍니다 — 작업을 분배하고, 소통하며, 사람의 세밀한 관리 없이 결과를 수렴합니다.

| | ClawTeam | 기타 멀티 에이전트 프레임워크 |
|---|---------|----------------------------|
| **사용 주체** | AI 에이전트 자체 | 오케스트레이션 코드를 작성하는 사람 |
| **설정** | `pip install` + 프롬프트 하나 | Docker, 클라우드 API, YAML 설정 |
| **인프라** | 파일 시스템 + tmux | Redis, 메시지 큐, 데이터베이스 |
| **에이전트 지원** | 모든 CLI 에이전트 | 프레임워크 전용만 |
| **격리** | Git 워크트리 (실제 브랜치) | 컨테이너 또는 가상 환경 |

---

## 작동 방식

<table>
<tr>
<td width="33%">

### 에이전트가 에이전트를 생성
리더가 `clawteam spawn`을 호출하여 워커를 생성합니다. 각 워커는 자체 **Git 워크트리**, **tmux 윈도우**, **아이덴티티**를 부여받습니다.

```bash
clawteam spawn --team my-team \
  --agent-name worker1 \
  --task "Implement auth module"
```

</td>
<td width="33%">

### 에이전트 간 대화
워커들은 수신함을 확인하고, 작업을 업데이트하며, 결과를 보고합니다 — 모두 프롬프트에 **자동 주입**되는 CLI 명령어를 통해.

```bash
clawteam task list my-team --owner me
clawteam inbox send my-team leader \
  "Auth done. All tests passing."
```

</td>
<td width="33%">

### 지켜보기만 하면 됩니다
타일형 tmux 뷰 또는 웹 UI에서 스웜을 모니터링하세요. 리더가 조율을 담당합니다.

```bash
clawteam board attach my-team
# Or web dashboard
clawteam board serve --port 8080
```

</td>
</tr>
</table>

---

## 빠른 시작

### 방법 1: 에이전트에게 맡기기 (권장)

ClawTeam을 설치한 후, 에이전트에게 프롬프트를 보내세요:

```
"Build a web app. Use clawteam to split the work across multiple agents."
```

에이전트가 자동으로 팀을 생성하고, 워커를 스폰하며, 작업을 할당하고, 조율합니다 — 모두 `clawteam` CLI를 통해.

### 방법 2: 직접 조작하기

```bash
# Create a team
clawteam team spawn-team my-team -d "Build the auth module" -n leader

# Spawn workers — each gets a git worktree + tmux window
clawteam spawn --team my-team --agent-name alice --task "Implement OAuth2 flow"
clawteam spawn --team my-team --agent-name bob   --task "Write unit tests for auth"

# Watch them work
clawteam board attach my-team
```

### 지원 에이전트

| 에이전트 | 스폰 명령어 | 상태 |
|-------|--------------|--------|
| [OpenClaw](https://openclaw.ai) | `clawteam spawn tmux openclaw --team ...` | **기본** |
| [Claude Code](https://claude.ai/claude-code) | `clawteam spawn tmux claude --team ...` | 완전 지원 |
| [Codex](https://openai.com/codex) | `clawteam spawn tmux codex --team ...` | 완전 지원 |
| [nanobot](https://github.com/HKUDS/nanobot) | `clawteam spawn tmux nanobot --team ...` | 완전 지원 |
| [Cursor](https://cursor.com) | `clawteam spawn subprocess cursor --team ...` | 실험적 |
| 커스텀 스크립트 | `clawteam spawn subprocess python --team ...` | 완전 지원 |

---

## 설치

### 단계 1: 사전 요구 사항

ClawTeam은 **Python 3.10+**, **tmux**, 그리고 최소 하나의 CLI 코딩 에이전트(OpenClaw, Claude Code, Codex 등)가 필요합니다.

**이미 설치된 항목 확인:**

```bash
python3 --version   # Need 3.10+
tmux -V             # Need any version
openclaw --version  # Or: claude --version / codex --version
```

**누락된 사전 요구 사항 설치:**

| 도구 | macOS | Ubuntu/Debian |
|------|-------|---------------|
| Python 3.10+ | `brew install python@3.12` | `sudo apt update && sudo apt install python3 python3-pip` |
| tmux | `brew install tmux` | `sudo apt install tmux` |
| OpenClaw | `pip install openclaw` | `pip install openclaw` |

> OpenClaw 대신 Claude Code 또는 Codex를 사용하는 경우, 해당 도구의 공식 문서에 따라 설치하세요. OpenClaw이 기본이지만 필수는 아닙니다.

### 단계 2: ClawTeam 설치

> **⚠️ `pip install clawteam` 또는 `npm install -g clawteam`을 직접 실행하지 마세요:**
> - `pip install clawteam`은 PyPI의 업스트림 버전을 설치하며, `claude`가 기본값이고 OpenClaw 적응이 없습니다.
> - `npm install -g clawteam`은 관련 없는 스쿼팅 패키지를 설치합니다 (게시자 `a9logic`). `clawteam --version`에서 "Coming Soon"이 표시되면 잘못된 패키지입니다. 먼저 `npm uninstall -g clawteam`으로 삭제하세요.
>
> **아래 세 가지 명령을 사용하세요 — clone 후 `pip install -e .`는 필수입니다. PyPI가 아닌 로컬 저장소에서 설치합니다.**

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
pip install -e .    # ← 필수! 로컬 저장소에서 설치. pip install clawteam과 다름
```

선택 사항 — P2P 전송 (ZeroMQ):

```bash
pip install -e ".[p2p]"
```

### 단계 3: `~/bin/clawteam` 심볼릭 링크 생성

스폰된 에이전트는 pip의 bin 디렉토리가 PATH에 없을 수 있는 새로운 셸에서 실행됩니다. `~/bin`에 심볼릭 링크를 만들면 `clawteam`에 항상 접근할 수 있습니다:

```bash
mkdir -p ~/bin
ln -sf "$(which clawteam)" ~/bin/clawteam
```

`which clawteam`이 아무것도 반환하지 않으면 수동으로 바이너리를 찾으세요:

```bash
# Common locations:
# ~/.local/bin/clawteam
# /opt/homebrew/bin/clawteam
# /usr/local/bin/clawteam
# /Library/Frameworks/Python.framework/Versions/3.*/bin/clawteam
find / -name clawteam -type f 2>/dev/null | head -5
```

그런 다음 `~/bin`이 PATH에 있는지 확인하세요 — 없다면 `~/.zshrc` 또는 `~/.bashrc`에 다음을 추가하세요:

```bash
export PATH="$HOME/bin:$PATH"
```

### 단계 4: OpenClaw 스킬 설치 (OpenClaw 사용자만)

스킬 파일은 OpenClaw 에이전트에게 자연어를 통해 ClawTeam 사용법을 알려줍니다. OpenClaw을 사용하지 않는 경우 이 단계를 건너뛰세요.

```bash
mkdir -p ~/.openclaw/workspace/skills/clawteam
cp skills/openclaw/SKILL.md ~/.openclaw/workspace/skills/clawteam/SKILL.md
```

### 단계 5: 실행 승인 구성 (OpenClaw 사용자만)

스폰된 OpenClaw 에이전트는 `clawteam` 명령어를 실행하기 위한 권한이 필요합니다. 이 설정이 없으면 에이전트가 대화형 권한 프롬프트에서 멈춥니다.

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

> `openclaw approvals`가 실패하면 OpenClaw 게이트웨이가 실행 중이 아닐 수 있습니다. 먼저 시작한 후 다시 시도하세요.

### 단계 6: 확인

```bash
clawteam --version          # Should print version
clawteam config health      # Should show all green
```

OpenClaw을 사용하는 경우, 스킬이 로드되었는지도 확인하세요:

```bash
openclaw skills list | grep clawteam
```

### 자동 설치

위의 단계 2~6은 단일 스크립트로도 실행할 수 있습니다:

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
bash scripts/install-openclaw.sh
```

### 문제 해결

| 문제 | 원인 | 해결 방법 |
|---------|-------|-----|
| `clawteam: command not found` | pip bin 디렉토리가 PATH에 없음 | 단계 3 실행 (심볼릭 링크 + PATH) |
| 스폰된 에이전트가 `clawteam`을 찾지 못함 | 에이전트가 pip PATH가 없는 새 셸에서 실행됨 | `~/bin/clawteam` 심볼릭 링크와 `~/bin`이 PATH에 있는지 확인 |
| `openclaw approvals` 실패 | 게이트웨이 미실행 | `openclaw gateway`를 먼저 시작한 후 단계 5 재시도 |
| `exec-approvals.json not found` | OpenClaw이 한 번도 실행된 적 없음 | `openclaw`을 한 번 실행하여 설정을 생성한 후 단계 5 재시도 |
| 에이전트가 권한 프롬프트에서 멈춤 | 실행 승인 보안이 "full"로 설정됨 | 단계 5를 실행하여 "allowlist"로 전환 |
| `pip install -e .` 실패 | 빌드 의존성 누락 | `pip install hatchling`을 먼저 실행 |
| `clawteam --version`에서 "Coming Soon" 표시 | npm 스쿼팅 패키지를 잘못 설치 (`a9logic`, 본 프로젝트와 무관) | `npm uninstall -g clawteam` 후 2단계에 따라 재설치 |

---

## 활용 사례

### 1. 자율 ML 연구 — 8 에이전트 x 8 GPU

[@karpathy/autoresearch](https://github.com/karpathy/autoresearch) 기반. 하나의 프롬프트로 H100 GPU 8대에 걸쳐 8개 연구 에이전트를 실행하여 2000개 이상의 실험을 자율적으로 설계합니다.

```
Human: "Use 8 GPUs to optimize train.py. Read program.md for instructions."

Leader agent:
├── 8개 에이전트를 스폰, 각각 연구 방향 할당 (깊이, 너비, 학습률, 배치 크기...)
├── 각 에이전트는 격리된 실험을 위한 자체 git 워크트리를 부여받음
├── 30분마다: 결과를 확인하고, 최적 설정을 새 에이전트에 교차 전파
├── 에이전트가 완료되면 GPU 재할당 — 새 에이전트는 최적 알려진 설정부터 시작
└── 결과: val_bpb 1.044 → 0.977 (6.4% 개선) 2430개 실험 / 약 30 GPU-시간
```

전체 결과: [novix-science/autoresearch](https://github.com/novix-science/autoresearch)

### 2. 에이전트 기반 소프트웨어 엔지니어링

```
Human: "Build a full-stack todo app with auth, database, and React frontend."

Leader agent:
├── 의존성 체인이 있는 작업 생성 (API 스키마 → 인증 + DB → 프론트엔드 → 테스트)
├── 별도 워크트리에 5개 에이전트 스폰 (아키텍트, 백엔드 2명, 프론트엔드, 테스터)
├── 의존성 자동 해결: 아키텍트 완료 → 백엔드 차단 해제 → 테스터 차단 해제
├── 에이전트들이 수신함을 통해 조율: "여기 OpenAPI 스펙입니다", "인증 엔드포인트 준비 완료"
└── 리더가 완료 시 모든 워크트리를 main에 병합
```

### 3. AI 헤지펀드 — 템플릿 실행

TOML 템플릿 하나로 7-에이전트 투자팀을 한 번의 명령으로 구성합니다:

```bash
clawteam launch hedge-fund --team fund1 --goal "Analyze AAPL, MSFT, NVDA for Q2 2026"
```

5개 애널리스트 에이전트(가치, 성장, 기술적 분석, 펀더멘털, 감성 분석)가 병렬로 작업합니다. 리스크 매니저가 모든 신호를 종합하고, 포트폴리오 매니저가 최종 결정을 내립니다.

템플릿은 TOML 파일입니다 — 어떤 도메인이든 **나만의 템플릿을 만들** 수 있습니다.

---

## 기능

<table>
<tr>
<td width="50%">

### 에이전트 자기 조직화
- 리더가 워커를 스폰하고 관리
- 자동 주입되는 조율 프롬프트 — 수동 설정 불필요
- 워커가 상태 및 유휴 상태를 자체 보고
- 모든 CLI 에이전트 참여 가능

### 작업 공간 격리
- 각 에이전트가 자체 **Git 워크트리**를 부여받음
- 병렬 에이전트 간 머지 충돌 없음
- 체크포인트, 머지, 정리 명령어 제공
- 브랜치 네이밍: `clawteam/{team}/{agent}`

### 의존성이 있는 작업 추적
- 공유 칸반: `pending` → `in_progress` → `completed` / `blocked`
- `--blocked-by` 체인으로 완료 시 자동 차단 해제
- `task wait`로 모든 작업 완료까지 대기

</td>
<td width="50%">

### 에이전트 간 메시징
- 포인트-투-포인트 수신함 (보내기, 받기, 미리보기)
- 전체 팀원에게 브로드캐스트
- 파일 기반 (기본) 또는 ZeroMQ P2P 전송

### 모니터링 및 대시보드
- `board show` — 터미널 칸반
- `board live` — 자동 새로고침 대시보드
- `board attach` — 모든 에이전트의 타일형 tmux 뷰
- `board serve` — 실시간 업데이트 웹 UI

### 팀 템플릿
- TOML 파일로 팀 아키타입 정의 (역할, 작업, 프롬프트)
- 단일 명령어: `clawteam launch <template>`
- 변수 치환: `{goal}`, `{team_name}`, `{agent_name}`
- **에이전트별 모델 할당** (프리뷰): 역할별로 다른 모델 지정 가능 — [아래 참조](#에이전트별-모델-할당-프리뷰)

</td>
</tr>
</table>

**추가 기능:** 플랜 승인 워크플로, 우아한 라이프사이클 관리, 모든 명령어에 `--json` 출력, 크로스 머신 지원 (NFS/SSHFS 또는 P2P), 멀티 유저 네임스페이싱, 자동 롤백을 포함한 스폰 검증, `fcntl` 파일 잠금으로 동시성 안전 보장.

---

## OpenClaw 통합

이 포크는 [OpenClaw](https://openclaw.ai)을 **기본 에이전트**로 만듭니다. ClawTeam 없이는 각 OpenClaw 에이전트가 독립적으로 작동합니다. ClawTeam이 이를 멀티 에이전트 플랫폼으로 변환합니다.

| 기능 | OpenClaw 단독 | OpenClaw + ClawTeam |
|-----------|---------------|-------------------|
| **작업 할당** | 에이전트별 수동 메시지 전달 | 리더가 자율적으로 분할, 할당, 모니터링 |
| **병렬 개발** | 공유 작업 디렉토리 | 에이전트별 격리된 Git 워크트리 |
| **의존성** | 수동 폴링 | `--blocked-by`와 자동 차단 해제 |
| **소통** | AGI 릴레이를 통해서만 | 직접 포인트-투-포인트 수신함 + 브로드캐스트 |
| **관찰성** | 로그 읽기 | 칸반 보드 + 타일형 tmux 뷰 |

스킬이 설치되면 아무 채널에서나 OpenClaw 봇과 대화하세요:

| 하는 말 | 수행되는 작업 |
|-------------|-------------|
| "웹 앱을 만들 5-에이전트 팀을 생성해" | 팀, 작업 생성 후 tmux에서 5개 에이전트 스폰 |
| "헤지펀드 분석 팀을 실행해" | 7개 에이전트로 `clawteam launch hedge-fund` 실행 |
| "에이전트 팀 상태를 확인해" | 칸반 출력과 함께 `clawteam board show` 실행 |

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

## 아키텍처

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

모든 상태는 `~/.clawteam/`에 JSON 파일로 저장됩니다. 데이터베이스도 서버도 필요 없습니다. `fcntl` 파일 잠금을 사용한 원자적 쓰기로 충돌 안전성을 보장합니다.

| 설정 | 환경 변수 | 기본값 |
|---------|---------|---------|
| 데이터 디렉토리 | `CLAWTEAM_DATA_DIR` | `~/.clawteam` |
| 전송 방식 | `CLAWTEAM_TRANSPORT` | `file` |
| 작업 공간 모드 | `CLAWTEAM_WORKSPACE` | `auto` |
| 스폰 백엔드 | `CLAWTEAM_DEFAULT_BACKEND` | `tmux` |

---

## 명령어 참조

<details open>
<summary><strong>핵심 명령어</strong></summary>

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
<summary><strong>작업 공간, 플랜, 라이프사이클, 설정</strong></summary>

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

## 에이전트별 모델 할당 (프리뷰)

> **브랜치:** [`feat/per-agent-model-assignment`](https://github.com/win4r/ClawTeam-OpenClaw/tree/feat/per-agent-model-assignment)
>
> 이 기능은 별도 브랜치에서 조기 테스트용으로 제공됩니다. 동반하는 OpenClaw `--model` 플래그가 출시되면 `main`에 병합될 예정입니다.

멀티 에이전트 스웜에서 비용/성능 트레이드오프를 최적화하기 위해 역할별로 다른 모델을 할당할 수 있습니다.

```bash
# Install from the feature branch
pip install -e "git+https://github.com/win4r/ClawTeam-OpenClaw.git@feat/per-agent-model-assignment#egg=clawteam"
```

**템플릿에서 에이전트별 모델 지정:**
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

**CLI 플래그:**
```bash
clawteam spawn --model opus                          # single agent
clawteam launch my-template --model gpt-5.4          # override all agents
clawteam launch my-template --model-strategy auto     # auto-assign by role
```

전체 기능 요청 및 논의는 [이슈 #1](https://github.com/win4r/ClawTeam-OpenClaw/issues/1)을 참조하세요.

---

## 로드맵

| 버전 | 내용 | 상태 |
|---------|------|--------|
| v0.3 | 파일 + P2P 전송, 웹 UI, 멀티 유저, 템플릿 | 출시 완료 |
| v0.4 | Redis 전송 — 크로스 머신 메시징 | 계획됨 |
| v0.5 | 공유 상태 레이어 — 머신 간 팀 설정 | 계획됨 |
| v0.6 | 에이전트 마켓플레이스 — 커뮤니티 템플릿 | 탐색 중 |
| v0.7 | 적응형 스케줄링 — 동적 작업 재할당 | 탐색 중 |
| v1.0 | 프로덕션 등급 — 인증, 권한, 감사 로그 | 탐색 중 |

---

## 기여하기

기여를 환영합니다:

- **에이전트 통합** — 더 많은 CLI 에이전트 지원
- **팀 템플릿** — 새로운 도메인을 위한 TOML 템플릿
- **전송 백엔드** — Redis, NATS 등
- **대시보드 개선** — 웹 UI, Grafana
- **문서화** — 튜토리얼 및 모범 사례

---

## 감사의 글

- [@karpathy/autoresearch](https://github.com/karpathy/autoresearch) — 자율 ML 연구 프레임워크
- [OpenClaw](https://openclaw.ai) — 기본 에이전트 백엔드
- [Claude Code](https://claude.ai/claude-code) 및 [Codex](https://openai.com/codex) — 지원되는 AI 코딩 에이전트
- [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) — 헤지펀드 템플릿 영감
- [CLI-Anything](https://github.com/HKUDS/CLI-Anything) — 자매 프로젝트

## 라이선스

MIT — 자유롭게 사용, 수정, 배포할 수 있습니다.

---

<div align="center">

**ClawTeam** — *에이전트 스웜 인텔리전스.*

</div>
