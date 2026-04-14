# ClawTeam Coordination Workflows

## Workflow 1: Create a Team and Assign Tasks

A common workflow for setting up a new project team.

```bash
# 1. Set leader identity
export CLAWTEAM_AGENT_ID="leader-001"
export CLAWTEAM_AGENT_NAME="leader"
export CLAWTEAM_AGENT_TYPE="leader"

# 2. Create team
clawteam team spawn-team my-project -d "Web app development" -n leader

# 3. Create tasks with dependencies
clawteam task create my-project "Design API schema" -o leader
# => Task ID: aaa11111

clawteam task create my-project "Implement backend" -o backend-dev --blocked-by aaa11111
# => Task ID: bbb22222 (auto-set to blocked status)

clawteam task create my-project "Build frontend" -o frontend-dev --blocked-by aaa11111
# => Task ID: ccc33333

clawteam task create my-project "Integration testing" --blocked-by bbb22222,ccc33333
# => Task ID: ddd44444

# 4. Check board
clawteam board show my-project

# 5. As tasks complete, update status (auto-unblocks dependents)
clawteam task update my-project aaa11111 --status completed
# bbb22222 and ccc33333 auto-unblock from blocked -> pending
```

## Workflow 2: Multi-Agent Spawn and Coordination

Full lifecycle of spawning multiple agents and coordinating work.

```bash
# Leader creates team
clawteam team spawn-team dev-team -d "Feature development" -n leader

# Spawn worker agents (each gets identity env vars automatically)
clawteam spawn tmux claude --team dev-team --agent-name researcher --agent-type researcher
clawteam spawn tmux claude --team dev-team --agent-name coder --agent-type general-purpose

# Leader creates tasks
clawteam task create dev-team "Research best practices" -o researcher
clawteam task create dev-team "Implement solution" -o coder

# Leader sends instructions via inbox
clawteam inbox send dev-team researcher "Research authentication patterns for microservices"
clawteam inbox send dev-team coder "Wait for researcher's findings before starting implementation"

# Monitor progress
clawteam board live dev-team --interval 5
```

### Worker Agent Perspective

From inside a spawned worker agent:

```bash
# Identity is pre-set via environment
clawteam identity show
# => agentName: researcher, teamName: dev-team

# Check inbox for instructions
clawteam inbox receive dev-team

# Do work, then update task
clawteam task update dev-team <task-id> --status in_progress
# ... work ...
clawteam task update dev-team <task-id> --status completed

# Notify leader when idle
clawteam lifecycle idle dev-team --last-task <task-id> --task-status completed
```

## Workflow 3: Join Request Protocol

When an agent wants to join an existing team dynamically.

```bash
# Agent side: request to join (blocks until response)
clawteam team request-join dev-team bob --capabilities "frontend specialist" --timeout 120

# Leader side: check inbox for join requests
clawteam inbox peek dev-team --agent leader
# => join_request from bob, requestId: join-abc123

# Leader approves
clawteam team approve-join dev-team join-abc123

# Agent receives approval with assigned name and agent ID
# => Approved! Joined as 'bob' (agentId: xyz789)
```

## Workflow 4: Plan Approval Flow

For teams requiring plan review before execution.

```bash
# Worker submits plan
clawteam plan submit dev-team coder "1. Refactor auth module\n2. Add OAuth2\n3. Update tests" \
  --summary "Auth system modernization"

# Leader reviews (checks inbox)
clawteam inbox receive dev-team --agent leader
# => plan_approval_request with planId

# Leader approves or rejects
clawteam plan approve dev-team <plan-id> coder --feedback "Looks good, proceed"
# or
clawteam plan reject dev-team <plan-id> coder --feedback "Add error handling section"
```

## Workflow 5: Graceful Shutdown

Coordinated shutdown of team agents.

```bash
# Leader requests shutdown of a worker
clawteam lifecycle request-shutdown dev-team leader coder --reason "All tasks complete"

# Worker checks inbox, sees shutdown request
clawteam inbox receive dev-team --agent coder
# => shutdown_request, requestId: shut-xyz

# Worker finishes current work, then approves
clawteam lifecycle approve-shutdown dev-team shut-xyz coder

# Leader cleans up team when all agents are done
clawteam team cleanup dev-team --force
```

## Workflow 6: Monitoring and Debugging

Using board and inbox commands to monitor team health.

```bash
# Quick overview of all teams
clawteam board overview

# Detailed view of one team
clawteam board show dev-team

# JSON output for scripting/parsing
clawteam --json board show dev-team | jq '.taskSummary'
clawteam --json task list dev-team --status blocked | jq '.[].subject'

# Check who has unread messages
clawteam --json board show dev-team | jq '.members[] | select(.inboxCount > 0) | .name'

# Live monitoring
clawteam board live dev-team --interval 3

# Watch a specific agent's inbox
clawteam inbox watch dev-team --agent leader
```

## Common Patterns

### Task with Dependencies

```bash
# Create a chain: A -> B -> C
clawteam task create team "Task A" -o alice
# ID: aaa
clawteam task create team "Task B" -o bob --blocked-by aaa
# ID: bbb (status: blocked)
clawteam task create team "Task C" -o carol --blocked-by bbb
# ID: ccc (status: blocked)

# When A completes, B auto-unblocks
clawteam task update team aaa --status completed
# B moves from blocked -> pending

# When B completes, C auto-unblocks
clawteam task update team bbb --status completed
```

### Broadcasting Updates

```bash
# Leader broadcasts to all team members
clawteam inbox broadcast dev-team "Sprint planning at 2pm. Check your tasks."

# Broadcast with routing key for filtering
clawteam inbox broadcast dev-team "Build passed" --key "ci-notification"
```

### Using JSON Output in Scripts

```bash
# Get all blocked tasks
BLOCKED=$(clawteam --json task list dev-team --status blocked)
echo "$BLOCKED" | jq -r '.[].id'

# Count pending messages per team
clawteam --json board overview | jq '.[] | "\(.name): \(.pendingMessages) pending"'

# Get team member names
clawteam --json team status dev-team | jq -r '.members[].name'
```

### Checking If an Agent Has Joined

When a leader agent spawns a worker and then polls to confirm it joined, the
correct signal is the team's `members` list — **not** a task's `owner` field.

#### ❌ Anti-pattern: relying on task.owner

```bash
# WRONG — task.owner is declarative, set at task-create time regardless of spawn outcome
OWNER=$(clawteam --json task get dev-team "$task_id" | jq -r '.owner')
if [[ -n "$OWNER" ]]; then
  echo "Agent joined"  # false positive: owner is set even when spawn failed
fi
```

A task's `owner` is written when the task is **created** (via `-o`). It declares
"who *should* do this work", not "who *actually joined the team*". A failed
`clawteam spawn` leaves the task's owner untouched, so monitor loops that poll
`task.owner` falsely see "already joined", skip the respawn, and block every
task that depends on that agent.

#### ✅ Correct pattern: check team.members

```bash
# `team.members` is backed by the spawn registry + is_agent_alive() — dead or
# never-joined agents are NOT listed here.
MEMBERS=$(clawteam --json team status dev-team | jq -r '.members[].name')

if ! grep -qw "db-designer" <<< "$MEMBERS"; then
  clawteam spawn tmux claude --team dev-team --agent-name db-designer \
    --task "Design user schema"
fi
```

**Rule of thumb:**

| Signal | Answers |
|--------|---------|
| `task.owner` | "Who *should* do this?" (declarative, write-once at create time) |
| `team.members` | "Who *is actually here*?" (live, backed by spawn registry) |

Only `team.members` is a reliable existence check in coordination loops.
