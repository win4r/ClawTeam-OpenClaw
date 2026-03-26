# Troubleshooting

## Tasks stuck in `in_progress` but no worker is actually running

### Symptoms

- Board shows tasks as `in_progress` with `locked by: <agent>`
- `tmux ls` shows no active session/window for that team
- Worker process is gone, but task lock remains

### Why it happens

If a worker exits unexpectedly (or tmux/session disappears) before normal lifecycle cleanup,
its lock can remain on the task.

### Recovery

Use stale-lock sweep + leader self-heal loop:

```bash
clawteam lifecycle sweep --team <team>
clawteam lifecycle leader-loop --team <team> --once
```

What they do:

1. Detect locks held by dead agents
2. Release stale locks
3. Move affected `in_progress` tasks back to `pending`
4. Attempt controlled auto-respawn of dead workers (backoff + retry budget)
5. Send recovery summary to team leader inbox

### Verify

```bash
clawteam board show <team>
clawteam task list <team>
```

Recovered tasks should no longer be locked and should be schedulable again.
