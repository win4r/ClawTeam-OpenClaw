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
  <strong>Coordenação de enxame multi-agente para agentes de codificação CLI — <a href="https://openclaw.ai">OpenClaw</a> como padrão</strong>
</p>

<p align="center">
  <a href="https://github.com/HKUDS/ClawTeam"><img src="https://img.shields.io/badge/upstream-HKUDS%2FClawTeam-purple?style=for-the-badge" alt="Upstream"></a>
  <a href="#-início-rápido"><img src="https://img.shields.io/badge/Quick_Start-3_min-blue?style=for-the-badge" alt="Início Rápido"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="Licença"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/agents-OpenClaw_%7C_Claude_Code_%7C_Codex_%7C_nanobot-blueviolet" alt="Agents">
  <img src="https://img.shields.io/badge/transport-File_%7C_ZeroMQ_P2P-orange" alt="Transport">
  <img src="https://img.shields.io/badge/version-0.3.0-teal" alt="Version">
</p>

> **Fork de [HKUDS/ClawTeam](https://github.com/HKUDS/ClawTeam)** com integração profunda ao OpenClaw: agente `openclaw` como padrão, isolamento de sessão por agente, autoconfiguração de aprovação de execução e backends de spawn robustecidos para produção. Todas as correções do upstream são sincronizadas.

Você define o objetivo. O enxame de agentes cuida do resto — criando workers, dividindo tarefas, coordenando e mesclando resultados.

Funciona com [OpenClaw](https://openclaw.ai) (padrão), [Claude Code](https://claude.ai/claude-code), [Codex](https://openai.com/codex), [nanobot](https://github.com/HKUDS/nanobot), [Cursor](https://cursor.com) e qualquer agente CLI.

---

## Por que ClawTeam?

Os agentes de IA atuais são poderosos, mas trabalham de forma **isolada**. O ClawTeam permite que os agentes se auto-organizem em equipes — dividindo trabalho, comunicando-se e convergindo em resultados sem microgerenciamento humano.

| | ClawTeam | Outros frameworks multi-agente |
|---|---------|----------------------------|
| **Quem usa** | Os próprios agentes de IA | Humanos escrevendo código de orquestração |
| **Configuração** | `pip install` + um prompt | Docker, APIs na nuvem, configs YAML |
| **Infraestrutura** | Sistema de arquivos + tmux | Redis, filas de mensagens, bancos de dados |
| **Suporte a agentes** | Qualquer agente CLI | Apenas específicos do framework |
| **Isolamento** | Git worktrees (branches reais) | Containers ou ambientes virtuais |

---

## Como funciona

<table>
<tr>
<td width="33%">

### Agentes geram agentes
O líder chama `clawteam spawn` para criar workers. Cada um recebe sua própria **git worktree**, **janela tmux** e **identidade**.

```bash
clawteam spawn --team my-team \
  --agent-name worker1 \
  --task "Implement auth module"
```

</td>
<td width="33%">

### Agentes conversam entre si
Workers verificam caixas de entrada, atualizam tarefas e reportam resultados — tudo através de comandos CLI **auto-injetados** no prompt.

```bash
clawteam task list my-team --owner me
clawteam inbox send my-team leader \
  "Auth done. All tests passing."
```

</td>
<td width="33%">

### Você só observa
Monitore o enxame a partir de uma visualização tmux em mosaico ou da Interface Web. O líder cuida da coordenação.

```bash
clawteam board attach my-team
# Or web dashboard
clawteam board serve --port 8080
```

</td>
</tr>
</table>

---

## Início rápido

### Opção 1: Deixe o agente conduzir (Recomendado)

Instale o ClawTeam e depois dê o prompt ao seu agente:

```
"Build a web app. Use clawteam to split the work across multiple agents."
```

O agente cria automaticamente uma equipe, gera workers, atribui tarefas e coordena — tudo via CLI `clawteam`.

### Opção 2: Conduza manualmente

```bash
# Create a team
clawteam team spawn-team my-team -d "Build the auth module" -n leader

# Spawn workers — each gets a git worktree + tmux window
clawteam spawn --team my-team --agent-name alice --task "Implement OAuth2 flow"
clawteam spawn --team my-team --agent-name bob   --task "Write unit tests for auth"

# Watch them work
clawteam board attach my-team
```

### Agentes suportados

| Agente | Comando de spawn | Status |
|-------|--------------|--------|
| [OpenClaw](https://openclaw.ai) | `clawteam spawn tmux openclaw --team ...` | **Padrão** |
| [Claude Code](https://claude.ai/claude-code) | `clawteam spawn tmux claude --team ...` | Suporte completo |
| [Codex](https://openai.com/codex) | `clawteam spawn tmux codex --team ...` | Suporte completo |
| [nanobot](https://github.com/HKUDS/nanobot) | `clawteam spawn tmux nanobot --team ...` | Suporte completo |
| [Cursor](https://cursor.com) | `clawteam spawn subprocess cursor --team ...` | Experimental |
| Scripts personalizados | `clawteam spawn subprocess python --team ...` | Suporte completo |

---

## Instalação

### Passo 1: Pré-requisitos

O ClawTeam requer **Python 3.10+**, **tmux** e pelo menos um agente de codificação CLI (OpenClaw, Claude Code, Codex, etc.).

**Verifique o que você já tem:**

```bash
python3 --version   # Need 3.10+
tmux -V             # Need any version
openclaw --version  # Or: claude --version / codex --version
```

**Instale os pré-requisitos faltantes:**

| Ferramenta | macOS | Ubuntu/Debian |
|------|-------|---------------|
| Python 3.10+ | `brew install python@3.12` | `sudo apt update && sudo apt install python3 python3-pip` |
| tmux | `brew install tmux` | `sudo apt install tmux` |
| OpenClaw | `pip install openclaw` | `pip install openclaw` |

> Se estiver usando Claude Code ou Codex em vez de OpenClaw, instale-os conforme suas respectivas documentações. OpenClaw é o padrão, mas não é estritamente obrigatório.

### Passo 2: Instalar o ClawTeam

> **⚠️ NÃO execute `pip install clawteam` ou `npm install -g clawteam` diretamente:**
> - `pip install clawteam` instala a versão upstream do PyPI, que usa `claude` como padrão e não possui adaptações OpenClaw.
> - `npm install -g clawteam` instala um pacote usurpador sem relação (publicado por `a9logic`). Se `clawteam --version` mostrar "Coming Soon", é o pacote errado. Execute primeiro `npm uninstall -g clawteam`.
>
> **Use os três comandos abaixo — o `pip install -e .` após o clone é obrigatório. Ele instala a partir do repositório local, não do PyPI.**

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
pip install -e .    # ← Obrigatório! Instala do repositório local, NÃO é o mesmo que pip install clawteam
```

Opcional — Transporte P2P (ZeroMQ):

```bash
pip install -e ".[p2p]"
```

### Passo 3: Criar o symlink `~/bin/clawteam`

Agentes criados rodam em shells novos que podem não ter o diretório bin do pip no PATH. Um symlink em `~/bin` garante que o `clawteam` esteja sempre acessível:

```bash
mkdir -p ~/bin
ln -sf "$(which clawteam)" ~/bin/clawteam
```

Se `which clawteam` não retornar nada, encontre o binário manualmente:

```bash
# Common locations:
# ~/.local/bin/clawteam
# /opt/homebrew/bin/clawteam
# /usr/local/bin/clawteam
# /Library/Frameworks/Python.framework/Versions/3.*/bin/clawteam
find / -name clawteam -type f 2>/dev/null | head -5
```

Depois certifique-se de que `~/bin` esteja no seu PATH — adicione isso ao `~/.zshrc` ou `~/.bashrc` se ainda não estiver:

```bash
export PATH="$HOME/bin:$PATH"
```

### Passo 4: Instalar a skill do OpenClaw (apenas para usuários do OpenClaw)

O arquivo de skill ensina os agentes OpenClaw a usar o ClawTeam através de linguagem natural. Pule este passo se não estiver usando OpenClaw.

```bash
mkdir -p ~/.openclaw/workspace/skills/clawteam
cp skills/openclaw/SKILL.md ~/.openclaw/workspace/skills/clawteam/SKILL.md
```

### Passo 5: Configurar aprovações de execução (apenas para usuários do OpenClaw)

Agentes OpenClaw criados precisam de permissão para executar comandos `clawteam`. Sem isso, os agentes ficarão bloqueados em prompts interativos de permissão.

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

> Se `openclaw approvals` falhar, o gateway do OpenClaw pode não estar em execução. Inicie-o primeiro e tente novamente.

### Passo 6: Verificar

```bash
clawteam --version          # Should print version
clawteam config health      # Should show all green
```

Se estiver usando OpenClaw, verifique também se a skill foi carregada:

```bash
openclaw skills list | grep clawteam
```

### Instalador automático

Os passos 2 a 6 acima também estão disponíveis como um único script:

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
bash scripts/install-openclaw.sh
```

### Solução de problemas

| Problema | Causa | Solução |
|---------|-------|-----|
| `clawteam: command not found` | Diretório bin do pip não está no PATH | Execute o Passo 3 (symlink + PATH) |
| Agentes criados não encontram o `clawteam` | Agentes rodam em shells novos sem o PATH do pip | Verifique se o symlink `~/bin/clawteam` existe e se `~/bin` está no PATH |
| `openclaw approvals` falha | Gateway não está em execução | Inicie o `openclaw gateway` primeiro e repita o Passo 5 |
| `exec-approvals.json not found` | OpenClaw nunca foi executado | Execute `openclaw` uma vez para gerar a configuração e repita o Passo 5 |
| Agentes bloqueiam em prompts de permissão | Segurança de aprovação de execução está em "full" | Execute o Passo 5 para mudar para "allowlist" |
| `pip install -e .` falha | Dependências de build ausentes | Execute `pip install hatchling` primeiro |
| `clawteam --version` mostra "Coming Soon" | Pacote npm usurpador instalado por engano (`a9logic`, sem relação com este projeto) | `npm uninstall -g clawteam`, depois reinstalar conforme o passo 2 |

---

## Casos de uso

### 1. Pesquisa autônoma de ML — 8 agentes x 8 GPUs

Baseado em [@karpathy/autoresearch](https://github.com/karpathy/autoresearch). Um único prompt lança 8 agentes de pesquisa em H100s que projetam mais de 2000 experimentos de forma autônoma.

```
Human: "Use 8 GPUs to optimize train.py. Read program.md for instructions."

Leader agent:
├── Spawns 8 agents, each assigned a research direction (depth, width, LR, batch size...)
├── Each agent gets its own git worktree for isolated experiments
├── Every 30 min: checks results, cross-pollinates best configs to new agents
├── Reassigns GPUs as agents finish — fresh agents start from best known config
└── Result: val_bpb 1.044 → 0.977 (6.4% improvement) across 2430 experiments in ~30 GPU-hours
```

Resultados completos: [novix-science/autoresearch](https://github.com/novix-science/autoresearch)

### 2. Engenharia de software agêntica

```
Human: "Build a full-stack todo app with auth, database, and React frontend."

Leader agent:
├── Creates tasks with dependency chains (API schema → auth + DB → frontend → tests)
├── Spawns 5 agents (architect, 2 backend, frontend, tester) in separate worktrees
├── Dependencies auto-resolve: architect completes → backend unblocks → tester unblocks
├── Agents coordinate via inbox: "Here's the OpenAPI spec", "Auth endpoints ready"
└── Leader merges all worktrees into main when complete
```

### 3. Fundo de investimento com IA — Lançamento via template

Um template TOML gera uma equipe completa de 7 agentes de investimento com um único comando:

```bash
clawteam launch hedge-fund --team fund1 --goal "Analyze AAPL, MSFT, NVDA for Q2 2026"
```

5 agentes analistas (valor, crescimento, técnico, fundamentalista, sentimento) trabalham em paralelo. O gerente de risco sintetiza todos os sinais. O gerente de portfólio toma as decisões finais.

Templates são arquivos TOML — **crie os seus próprios** para qualquer domínio.

---

## Funcionalidades

<table>
<tr>
<td width="50%">

### Auto-organização de agentes
- O líder cria e gerencia workers
- Prompt de coordenação auto-injetado — zero configuração manual
- Workers reportam automaticamente status e estado ocioso
- Qualquer agente CLI pode participar

### Isolamento de workspace
- Cada agente recebe sua própria **git worktree**
- Sem conflitos de merge entre agentes paralelos
- Comandos de checkpoint, merge e limpeza
- Nomenclatura de branches: `clawteam/{team}/{agent}`

### Rastreamento de tarefas com dependências
- Kanban compartilhado: `pending` → `in_progress` → `completed` / `blocked`
- Cadeias `--blocked-by` com desbloqueio automático ao completar
- `task wait` bloqueia até que todas as tarefas sejam concluídas

</td>
<td width="50%">

### Mensagens entre agentes
- Caixas de entrada ponto-a-ponto (enviar, receber, espiar)
- Broadcast para todos os membros da equipe
- Transporte baseado em arquivo (padrão) ou ZeroMQ P2P

### Monitoramento e painéis
- `board show` — kanban no terminal
- `board live` — painel com atualização automática
- `board attach` — visualização tmux em mosaico de todos os agentes
- `board serve` — Interface Web com atualizações em tempo real

### Templates de equipe
- Arquivos TOML definem arquétipos de equipe (papéis, tarefas, prompts)
- Um comando: `clawteam launch <template>`
- Substituição de variáveis: `{goal}`, `{team_name}`, `{agent_name}`
- **Atribuição de modelo por agente** (prévia): atribua modelos diferentes a papéis diferentes — veja [abaixo](#atribuição-de-modelo-por-agente-prévia)

</td>
</tr>
</table>

**Também:** fluxos de aprovação de planos, gerenciamento gracioso de ciclo de vida, saída `--json` em todos os comandos, suporte entre máquinas (NFS/SSHFS ou P2P), namespacing multi-usuário, validação de spawn com rollback automático, travamento de arquivos `fcntl` para segurança em concorrência.

---

## Integração com OpenClaw

Este fork torna o [OpenClaw](https://openclaw.ai) o **agente padrão**. Sem o ClawTeam, cada agente OpenClaw trabalha isoladamente. O ClawTeam o transforma em uma plataforma multi-agente.

| Capacidade | OpenClaw sozinho | OpenClaw + ClawTeam |
|-----------|---------------|-------------------|
| **Atribuição de tarefas** | Mensagens manuais por agente | O líder divide, atribui e monitora autonomamente |
| **Desenvolvimento paralelo** | Diretório de trabalho compartilhado | Git worktrees isoladas por agente |
| **Dependências** | Polling manual | `--blocked-by` com desbloqueio automático |
| **Comunicação** | Apenas através do relay AGI | Caixa de entrada ponto-a-ponto direta + broadcast |
| **Observabilidade** | Ler logs | Quadro kanban + visualização tmux em mosaico |

Após a skill ser instalada, converse com seu bot OpenClaw em qualquer canal:

| O que você diz | O que acontece |
|-------------|-------------|
| "Crie uma equipe de 5 agentes para construir um app web" | Cria equipe, tarefas e gera 5 agentes no tmux |
| "Lance uma equipe de análise de fundo de investimento" | `clawteam launch hedge-fund` com 7 agentes |
| "Verifique o status da minha equipe de agentes" | `clawteam board show` com saída kanban |

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

## Arquitetura

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

Todo o estado fica em `~/.clawteam/` como arquivos JSON. Sem banco de dados, sem servidor. Escritas atômicas com travamento de arquivos `fcntl` garantem segurança contra falhas.

| Configuração | Variável de ambiente | Padrão |
|---------|---------|---------|
| Diretório de dados | `CLAWTEAM_DATA_DIR` | `~/.clawteam` |
| Transporte | `CLAWTEAM_TRANSPORT` | `file` |
| Modo de workspace | `CLAWTEAM_WORKSPACE` | `auto` |
| Backend de spawn | `CLAWTEAM_DEFAULT_BACKEND` | `tmux` |

---

## Referência de comandos

<details open>
<summary><strong>Comandos principais</strong></summary>

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
<summary><strong>Workspace, plano, ciclo de vida, configuração</strong></summary>

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

## Atribuição de modelo por agente (Prévia)

> **Branch:** [`feat/per-agent-model-assignment`](https://github.com/win4r/ClawTeam-OpenClaw/tree/feat/per-agent-model-assignment)
>
> Esta funcionalidade está disponível para testes antecipados em uma branch separada. Será mesclada na `main` assim que a flag `--model` complementar do OpenClaw for lançada.

Atribua modelos diferentes a papéis de agentes diferentes para melhores compensações de custo/desempenho em enxames multi-agente.

```bash
# Install from the feature branch
pip install -e "git+https://github.com/win4r/ClawTeam-OpenClaw.git@feat/per-agent-model-assignment#egg=clawteam"
```

**Modelo por agente em templates:**
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

**Flags de CLI:**
```bash
clawteam spawn --model opus                          # single agent
clawteam launch my-template --model gpt-5.4          # override all agents
clawteam launch my-template --model-strategy auto     # auto-assign by role
```

Veja a [issue #1](https://github.com/win4r/ClawTeam-OpenClaw/issues/1) para a solicitação completa da funcionalidade e discussão.

---

## Roteiro

| Versão | O quê | Status |
|---------|------|--------|
| v0.3 | Transporte por arquivo + P2P, Interface Web, multi-usuário, templates | Lançado |
| v0.4 | Transporte Redis — mensagens entre máquinas | Planejado |
| v0.5 | Camada de estado compartilhado — configuração de equipe entre máquinas | Planejado |
| v0.6 | Marketplace de agentes — templates da comunidade | Em exploração |
| v0.7 | Agendamento adaptativo — reatribuição dinâmica de tarefas | Em exploração |
| v1.0 | Grau de produção — autenticação, permissões, logs de auditoria | Em exploração |

---

## Contribuindo

Contribuições são bem-vindas:

- **Integrações de agentes** — suporte para mais agentes CLI
- **Templates de equipe** — templates TOML para novos domínios
- **Backends de transporte** — Redis, NATS, etc.
- **Melhorias no painel** — Interface Web, Grafana
- **Documentação** — tutoriais e boas práticas

---

## Agradecimentos

- [@karpathy/autoresearch](https://github.com/karpathy/autoresearch) — framework de pesquisa autônoma de ML
- [OpenClaw](https://openclaw.ai) — backend de agente padrão
- [Claude Code](https://claude.ai/claude-code) e [Codex](https://openai.com/codex) — agentes de codificação com IA suportados
- [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) — inspiração para o template de fundo de investimento
- [CLI-Anything](https://github.com/HKUDS/CLI-Anything) — projeto irmão

## Licença

MIT — livre para uso, modificação e distribuição.

---

<div align="center">

**ClawTeam** — *Inteligência de enxame de agentes.*

</div>
