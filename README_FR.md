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
  <strong>Coordination multi-agents en essaim pour agents de codage CLI — <a href="https://openclaw.ai">OpenClaw</a> par défaut</strong>
</p>

<p align="center">
  <a href="https://github.com/HKUDS/ClawTeam"><img src="https://img.shields.io/badge/upstream-HKUDS%2FClawTeam-purple?style=for-the-badge" alt="Upstream"></a>
  <a href="#-démarrage-rapide"><img src="https://img.shields.io/badge/Quick_Start-3_min-blue?style=for-the-badge" alt="Démarrage rapide"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="Licence"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/agents-OpenClaw_%7C_Claude_Code_%7C_Codex_%7C_nanobot-blueviolet" alt="Agents">
  <img src="https://img.shields.io/badge/transport-File_%7C_ZeroMQ_P2P-orange" alt="Transport">
  <img src="https://img.shields.io/badge/version-0.3.0-teal" alt="Version">
</p>

> **Fork de [HKUDS/ClawTeam](https://github.com/HKUDS/ClawTeam)** avec intégration approfondie d'OpenClaw : agent `openclaw` par défaut, isolation de session par agent, configuration automatique des autorisations d'exécution, et backends de lancement renforcés pour la production. Toutes les corrections upstream sont synchronisées.

Vous définissez l'objectif. L'essaim d'agents s'occupe du reste — lancement de travailleurs, répartition des tâches, coordination et fusion des résultats.

Compatible avec [OpenClaw](https://openclaw.ai) (par défaut), [Claude Code](https://claude.ai/claude-code), [Codex](https://openai.com/codex), [nanobot](https://github.com/HKUDS/nanobot), [Cursor](https://cursor.com), et tout agent CLI.

---

## Pourquoi ClawTeam ?

Les agents IA actuels sont puissants mais travaillent de manière **isolée**. ClawTeam permet aux agents de s'auto-organiser en équipes — répartissant le travail, communiquant et convergeant vers des résultats sans micro-gestion humaine.

| | ClawTeam | Autres frameworks multi-agents |
|---|---------|----------------------------|
| **Qui l'utilise** | Les agents IA eux-mêmes | Les humains écrivant du code d'orchestration |
| **Mise en place** | `pip install` + un prompt | Docker, API cloud, fichiers YAML |
| **Infrastructure** | Système de fichiers + tmux | Redis, files de messages, bases de données |
| **Support d'agents** | Tout agent CLI | Spécifique au framework uniquement |
| **Isolation** | Git worktrees (vraies branches) | Conteneurs ou environnements virtuels |

---

## Comment ça marche

<table>
<tr>
<td width="33%">

### Les agents engendrent des agents
Le leader appelle `clawteam spawn` pour créer des travailleurs. Chacun obtient son propre **git worktree**, sa **fenêtre tmux** et son **identité**.

```bash
clawteam spawn --team my-team \
  --agent-name worker1 \
  --task "Implement auth module"
```

</td>
<td width="33%">

### Les agents communiquent entre eux
Les travailleurs consultent leurs boîtes de réception, mettent à jour les tâches et rapportent les résultats — le tout via des commandes CLI **auto-injectées** dans leur prompt.

```bash
clawteam task list my-team --owner me
clawteam inbox send my-team leader \
  "Auth done. All tests passing."
```

</td>
<td width="33%">

### Vous observez simplement
Surveillez l'essaim depuis une vue tmux en mosaïque ou l'interface Web. Le leader gère la coordination.

```bash
clawteam board attach my-team
# Or web dashboard
clawteam board serve --port 8080
```

</td>
</tr>
</table>

---

## Démarrage rapide

### Option 1 : Laisser l'agent piloter (Recommandé)

Installez ClawTeam, puis donnez cette instruction à votre agent :

```
"Build a web app. Use clawteam to split the work across multiple agents."
```

L'agent crée automatiquement une équipe, lance des travailleurs, assigne les tâches et coordonne — le tout via la CLI `clawteam`.

### Option 2 : Piloter manuellement

```bash
# Create a team
clawteam team spawn-team my-team -d "Build the auth module" -n leader

# Spawn workers — each gets a git worktree + tmux window
clawteam spawn --team my-team --agent-name alice --task "Implement OAuth2 flow"
clawteam spawn --team my-team --agent-name bob   --task "Write unit tests for auth"

# Watch them work
clawteam board attach my-team
```

### Agents supportés

| Agent | Commande de lancement | Statut |
|-------|--------------|--------|
| [OpenClaw](https://openclaw.ai) | `clawteam spawn tmux openclaw --team ...` | **Par défaut** |
| [Claude Code](https://claude.ai/claude-code) | `clawteam spawn tmux claude --team ...` | Support complet |
| [Codex](https://openai.com/codex) | `clawteam spawn tmux codex --team ...` | Support complet |
| [nanobot](https://github.com/HKUDS/nanobot) | `clawteam spawn tmux nanobot --team ...` | Support complet |
| [Cursor](https://cursor.com) | `clawteam spawn subprocess cursor --team ...` | Expérimental |
| Scripts personnalisés | `clawteam spawn subprocess python --team ...` | Support complet |

---

## Installation

### Étape 1 : Prérequis

ClawTeam nécessite **Python 3.10+**, **tmux**, et au moins un agent de codage CLI (OpenClaw, Claude Code, Codex, etc.).

**Vérifiez ce que vous avez déjà :**

```bash
python3 --version   # Need 3.10+
tmux -V             # Need any version
openclaw --version  # Or: claude --version / codex --version
```

**Installez les prérequis manquants :**

| Outil | macOS | Ubuntu/Debian |
|------|-------|---------------|
| Python 3.10+ | `brew install python@3.12` | `sudo apt update && sudo apt install python3 python3-pip` |
| tmux | `brew install tmux` | `sudo apt install tmux` |
| OpenClaw | `pip install openclaw` | `pip install openclaw` |

> Si vous utilisez Claude Code ou Codex au lieu d'OpenClaw, installez-les selon leur propre documentation. OpenClaw est l'agent par défaut mais n'est pas strictement requis.

### Étape 2 : Installer ClawTeam

> **⚠️ N'exécutez PAS `pip install clawteam` ou `npm install -g clawteam` directement :**
> - `pip install clawteam` installe la version upstream depuis PyPI, qui utilise `claude` par défaut et ne contient pas les adaptations OpenClaw.
> - `npm install -g clawteam` installe un paquet usurpateur sans lien (éditeur `a9logic`). Si `clawteam --version` affiche "Coming Soon", c'est le mauvais paquet. Exécutez d'abord `npm uninstall -g clawteam`.
>
> **Utilisez les trois commandes ci-dessous — le `pip install -e .` après le clone est obligatoire. Il installe depuis le dépôt local, pas depuis PyPI.**

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
pip install -e .    # ← Obligatoire ! Installe depuis le dépôt local, PAS identique à pip install clawteam
```

Optionnel — Transport P2P (ZeroMQ) :

```bash
pip install -e ".[p2p]"
```

### Étape 3 : Créer le lien symbolique `~/bin/clawteam`

Les agents lancés s'exécutent dans des shells vierges qui n'ont pas forcément le répertoire bin de pip dans le PATH. Un lien symbolique dans `~/bin` garantit que `clawteam` est toujours accessible :

```bash
mkdir -p ~/bin
ln -sf "$(which clawteam)" ~/bin/clawteam
```

Si `which clawteam` ne retourne rien, trouvez le binaire manuellement :

```bash
# Common locations:
# ~/.local/bin/clawteam
# /opt/homebrew/bin/clawteam
# /usr/local/bin/clawteam
# /Library/Frameworks/Python.framework/Versions/3.*/bin/clawteam
find / -name clawteam -type f 2>/dev/null | head -5
```

Puis assurez-vous que `~/bin` est dans votre PATH — ajoutez ceci à `~/.zshrc` ou `~/.bashrc` si ce n'est pas le cas :

```bash
export PATH="$HOME/bin:$PATH"
```

### Étape 4 : Installer le skill OpenClaw (utilisateurs OpenClaw uniquement)

Le fichier skill apprend aux agents OpenClaw comment utiliser ClawTeam en langage naturel. Ignorez cette étape si vous n'utilisez pas OpenClaw.

```bash
mkdir -p ~/.openclaw/workspace/skills/clawteam
cp skills/openclaw/SKILL.md ~/.openclaw/workspace/skills/clawteam/SKILL.md
```

### Étape 5 : Configurer les autorisations d'exécution (utilisateurs OpenClaw uniquement)

Les agents OpenClaw lancés ont besoin de la permission d'exécuter les commandes `clawteam`. Sans cela, les agents seront bloqués par des invites de permission interactives.

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

> Si `openclaw approvals` échoue, la passerelle OpenClaw n'est peut-être pas en cours d'exécution. Démarrez-la d'abord, puis réessayez.

### Étape 6 : Vérification

```bash
clawteam --version          # Should print version
clawteam config health      # Should show all green
```

Si vous utilisez OpenClaw, vérifiez également que le skill est chargé :

```bash
openclaw skills list | grep clawteam
```

### Installateur automatisé

Les étapes 2 à 6 ci-dessus sont également disponibles via un script unique :

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
bash scripts/install-openclaw.sh
```

### Dépannage

| Problème | Cause | Solution |
|---------|-------|-----|
| `clawteam: command not found` | Répertoire bin de pip absent du PATH | Exécutez l'Étape 3 (lien symbolique + PATH) |
| Les agents lancés ne trouvent pas `clawteam` | Les agents s'exécutent dans des shells vierges sans le PATH de pip | Vérifiez que le lien symbolique `~/bin/clawteam` existe et que `~/bin` est dans le PATH |
| `openclaw approvals` échoue | Passerelle non en cours d'exécution | Démarrez `openclaw gateway` d'abord, puis réessayez l'Étape 5 |
| `exec-approvals.json not found` | OpenClaw n'a jamais été exécuté | Exécutez `openclaw` une fois pour générer la configuration, puis réessayez l'Étape 5 |
| Les agents sont bloqués par les invites de permission | La sécurité des autorisations d'exécution est en mode "full" | Exécutez l'Étape 5 pour passer en mode "allowlist" |
| `pip install -e .` échoue | Dépendances de build manquantes | Exécutez d'abord `pip install hatchling` |
| `clawteam --version` affiche "Coming Soon" | Paquet npm usurpateur installé par erreur (`a9logic`, sans lien avec ce projet) | `npm uninstall -g clawteam`, puis réinstaller selon l'étape 2 |

---

## Cas d'utilisation

### 1. Recherche ML autonome — 8 agents x 8 GPU

Basé sur [@karpathy/autoresearch](https://github.com/karpathy/autoresearch). Un seul prompt lance 8 agents de recherche sur des H100 qui conçoivent plus de 2000 expériences de manière autonome.

```
Human: "Use 8 GPUs to optimize train.py. Read program.md for instructions."

Leader agent:
├── Lance 8 agents, chacun assigné à une direction de recherche (profondeur, largeur, LR, taille de batch...)
├── Chaque agent obtient son propre git worktree pour des expériences isolées
├── Toutes les 30 min : vérifie les résultats, croise les meilleures configurations vers de nouveaux agents
├── Réassigne les GPU à mesure que les agents terminent — les nouveaux agents démarrent depuis la meilleure configuration connue
└── Résultat : val_bpb 1.044 → 0.977 (amélioration de 6.4%) sur 2430 expériences en ~30 heures-GPU
```

Résultats complets : [novix-science/autoresearch](https://github.com/novix-science/autoresearch)

### 2. Ingénierie logicielle agentique

```
Human: "Build a full-stack todo app with auth, database, and React frontend."

Leader agent:
├── Crée des tâches avec chaînes de dépendances (schéma API → auth + BD → frontend → tests)
├── Lance 5 agents (architecte, 2 backend, frontend, testeur) dans des worktrees séparés
├── Les dépendances se résolvent automatiquement : architecte terminé → backend débloqué → testeur débloqué
├── Les agents coordonnent via la boîte de réception : "Voici la spéc OpenAPI", "Endpoints d'auth prêts"
└── Le leader fusionne tous les worktrees dans main une fois terminé
```

### 3. Hedge Fund IA — Lancement par template

Un template TOML lance une équipe d'investissement complète de 7 agents en une seule commande :

```bash
clawteam launch hedge-fund --team fund1 --goal "Analyze AAPL, MSFT, NVDA for Q2 2026"
```

5 agents analystes (valeur, croissance, technique, fondamentaux, sentiment) travaillent en parallèle. Le gestionnaire de risques synthétise tous les signaux. Le gestionnaire de portefeuille prend les décisions finales.

Les templates sont des fichiers TOML — **créez les vôtres** pour n'importe quel domaine.

---

## Fonctionnalités

<table>
<tr>
<td width="50%">

### Auto-organisation des agents
- Le leader lance et gère les travailleurs
- Prompt de coordination auto-injecté — aucune configuration manuelle
- Les travailleurs rapportent automatiquement leur statut et leur état d'inactivité
- Tout agent CLI peut participer

### Isolation de l'espace de travail
- Chaque agent obtient son propre **git worktree**
- Aucun conflit de fusion entre agents parallèles
- Commandes de checkpoint, fusion et nettoyage
- Nommage des branches : `clawteam/{team}/{agent}`

### Suivi des tâches avec dépendances
- Kanban partagé : `pending` → `in_progress` → `completed` / `blocked`
- Chaînes `--blocked-by` avec déblocage automatique à l'achèvement
- `task wait` bloque jusqu'à ce que toutes les tâches soient terminées

</td>
<td width="50%">

### Messagerie inter-agents
- Boîtes de réception point à point (envoyer, recevoir, consulter)
- Diffusion à tous les membres de l'équipe
- Transport par fichier (par défaut) ou ZeroMQ P2P

### Surveillance et tableaux de bord
- `board show` — kanban en terminal
- `board live` — tableau de bord auto-rafraîchi
- `board attach` — vue tmux en mosaïque de tous les agents
- `board serve` — interface Web avec mises à jour en temps réel

### Templates d'équipe
- Les fichiers TOML définissent des archétypes d'équipe (rôles, tâches, prompts)
- Une seule commande : `clawteam launch <template>`
- Substitution de variables : `{goal}`, `{team_name}`, `{agent_name}`
- **Attribution de modèle par agent** (aperçu) : assignez différents modèles à différents rôles — voir [ci-dessous](#attribution-de-modèle-par-agent-aperçu)

</td>
</tr>
</table>

**Aussi :** workflows d'approbation de plans, gestion de cycle de vie gracieuse, sortie `--json` sur toutes les commandes, support multi-machines (NFS/SSHFS ou P2P), espaces de noms multi-utilisateurs, validation du lancement avec rollback automatique, verrouillage de fichiers `fcntl` pour la sécurité en accès concurrent.

---

## Intégration OpenClaw

Ce fork fait d'[OpenClaw](https://openclaw.ai) l'**agent par défaut**. Sans ClawTeam, chaque agent OpenClaw travaille de manière isolée. ClawTeam le transforme en une plateforme multi-agents.

| Capacité | OpenClaw seul | OpenClaw + ClawTeam |
|-----------|---------------|-------------------|
| **Attribution des tâches** | Messagerie manuelle par agent | Le leader divise, assigne et surveille de manière autonome |
| **Développement parallèle** | Répertoire de travail partagé | Git worktrees isolés par agent |
| **Dépendances** | Vérification manuelle | `--blocked-by` avec déblocage automatique |
| **Communication** | Uniquement via le relais AGI | Boîte de réception point à point directe + diffusion |
| **Observabilité** | Lecture des logs | Tableau kanban + vue tmux en mosaïque |

Une fois le skill installé, parlez à votre bot OpenClaw dans n'importe quel canal :

| Ce que vous dites | Ce qui se passe |
|-------------|-------------|
| "Crée une équipe de 5 agents pour construire une application web" | Crée l'équipe, les tâches, lance 5 agents dans tmux |
| "Lance une équipe d'analyse hedge-fund" | `clawteam launch hedge-fund` avec 7 agents |
| "Vérifie le statut de mon équipe d'agents" | `clawteam board show` avec sortie kanban |

```
  Vous (Telegram/Discord/TUI)
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

## Architecture

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

Tout l'état réside dans `~/.clawteam/` sous forme de fichiers JSON. Pas de base de données, pas de serveur. Les écritures atomiques avec verrouillage de fichiers `fcntl` garantissent la sécurité en cas de crash.

| Paramètre | Variable d'env. | Valeur par défaut |
|---------|---------|---------|
| Répertoire des données | `CLAWTEAM_DATA_DIR` | `~/.clawteam` |
| Transport | `CLAWTEAM_TRANSPORT` | `file` |
| Mode d'espace de travail | `CLAWTEAM_WORKSPACE` | `auto` |
| Backend de lancement | `CLAWTEAM_DEFAULT_BACKEND` | `tmux` |

---

## Référence des commandes

<details open>
<summary><strong>Commandes principales</strong></summary>

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
<summary><strong>Espace de travail, Plan, Cycle de vie, Configuration</strong></summary>

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

## Attribution de modèle par agent (Aperçu)

> **Branche :** [`feat/per-agent-model-assignment`](https://github.com/win4r/ClawTeam-OpenClaw/tree/feat/per-agent-model-assignment)
>
> Cette fonctionnalité est disponible pour des tests préliminaires sur une branche séparée. Elle sera fusionnée dans `main` une fois que le flag `--model` compagnon d'OpenClaw sera livré.

Assignez différents modèles à différents rôles d'agents pour de meilleurs compromis coût/performance dans les essaims multi-agents.

```bash
# Install from the feature branch
pip install -e "git+https://github.com/win4r/ClawTeam-OpenClaw.git@feat/per-agent-model-assignment#egg=clawteam"
```

**Modèle par agent dans les templates :**
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

**Flags CLI :**
```bash
clawteam spawn --model opus                          # single agent
clawteam launch my-template --model gpt-5.4          # override all agents
clawteam launch my-template --model-strategy auto     # auto-assign by role
```

Voir [issue #1](https://github.com/win4r/ClawTeam-OpenClaw/issues/1) pour la demande de fonctionnalité complète et la discussion.

---

## Feuille de route

| Version | Contenu | Statut |
|---------|------|--------|
| v0.3 | Transport fichier + P2P, interface Web, multi-utilisateurs, templates | Livré |
| v0.4 | Transport Redis — messagerie inter-machines | Prévu |
| v0.5 | Couche d'état partagé — configuration d'équipe inter-machines | Prévu |
| v0.6 | Marketplace d'agents — templates communautaires | En exploration |
| v0.7 | Planification adaptative — réassignation dynamique des tâches | En exploration |
| v1.0 | Qualité production — authentification, permissions, journaux d'audit | En exploration |

---

## Contribuer

Les contributions sont les bienvenues :

- **Intégrations d'agents** — support de nouveaux agents CLI
- **Templates d'équipe** — templates TOML pour de nouveaux domaines
- **Backends de transport** — Redis, NATS, etc.
- **Améliorations du tableau de bord** — interface Web, Grafana
- **Documentation** — tutoriels et bonnes pratiques

---

## Remerciements

- [@karpathy/autoresearch](https://github.com/karpathy/autoresearch) — framework de recherche ML autonome
- [OpenClaw](https://openclaw.ai) — backend d'agent par défaut
- [Claude Code](https://claude.ai/claude-code) et [Codex](https://openai.com/codex) — agents de codage IA supportés
- [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) — inspiration pour le template hedge fund
- [CLI-Anything](https://github.com/HKUDS/CLI-Anything) — projet frère

## Licence

MIT — libre d'utilisation, de modification et de distribution.

---

<div align="center">

**ClawTeam** — *Intelligence en essaim d'agents.*

</div>
