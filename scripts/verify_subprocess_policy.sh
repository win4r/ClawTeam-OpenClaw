#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <team-name>"
  exit 1
fi

TEAM="$1"

echo "[1/6] Ensure default backend is subprocess"
/opt/clawteam-openclaw-venv/bin/clawteam config set default_backend subprocess >/dev/null
/opt/clawteam-openclaw-venv/bin/clawteam config get default_backend

echo "[2/6] Verify team exists"
DATA_DIR=$(/opt/clawteam-openclaw-venv/bin/python - <<'PY'
from clawteam.team.models import get_data_dir
print(get_data_dir())
PY
)
TEAM_JSON="$DATA_DIR/teams/$TEAM/team.json"
if [[ ! -f "$TEAM_JSON" ]]; then
  ALT_TEAM_JSON="/var/lib/clawteam/teams/$TEAM/team.json"
  if [[ -f "$ALT_TEAM_JSON" ]]; then
    DATA_DIR="/var/lib/clawteam"
    TEAM_JSON="$ALT_TEAM_JSON"
  else
    echo "team not found: $TEAM ($TEAM_JSON or $ALT_TEAM_JSON)"
    exit 2
  fi
fi

echo "[3/6] Force old-state simulation (tmux policy + permanent_failure=true)"
python3 - <<PY
import json
from pathlib import Path
team = ${TEAM@Q}
p = Path(f"/var/lib/clawteam/teams/{team}/leader_loop_state.json")
state = {"agents": {}}
if p.exists():
    try:
        state = json.loads(p.read_text())
    except Exception:
        state = {"agents": {}}

# stamp all non-leader members if registry exists
reg_path = Path(f"/var/lib/clawteam/teams/{team}/spawn_registry.json")
agents = []
if reg_path.exists():
    try:
        reg = json.loads(reg_path.read_text())
        agents = [a for a in reg.keys() if a != "leader"]
    except Exception:
        pass

if not agents:
    # fallback: seed a generic worker name to validate parser behaviour
    agents = ["worker1"]

for a in agents:
    state.setdefault("agents", {})[a] = {
        "attempts": 2,
        "last_attempt": 9999999999.0,
        "permanent_failure": True,
        "last_error": "old",
        "backend_policy": "tmux",
    }

p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"seeded {len(agents)} agent state(s) into", p)
PY

echo "[4/6] Trigger one leader-loop iteration"
/opt/clawteam-openclaw-venv/bin/clawteam lifecycle leader-loop --team "$TEAM" --once || true

echo "[5/6] Inspect leader_loop_state backend_policy/permanent_failure"
python3 - <<PY
import json
from pathlib import Path
team = ${TEAM@Q}
p = Path(f"/var/lib/clawteam/teams/{team}/leader_loop_state.json")
state = json.loads(p.read_text()) if p.exists() else {"agents":{}}
for name, s in sorted(state.get("agents", {}).items()):
    print(name, "policy=", s.get("backend_policy"), "permanent_failure=", s.get("permanent_failure"), "attempts=", s.get("attempts"))
PY

echo "[6/6] Inspect spawn registry backend distribution"
python3 - <<PY
import json
from pathlib import Path
team = ${TEAM@Q}
p = Path(f"/var/lib/clawteam/teams/{team}/spawn_registry.json")
if not p.exists():
    print("spawn_registry missing")
    raise SystemExit(0)
reg = json.loads(p.read_text())
backs = {}
for a, info in reg.items():
    b = info.get("backend", "")
    backs[b] = backs.get(b, 0) + 1
print("backend_counts", backs)
for a, info in sorted(reg.items()):
    print(a, info.get("backend"), info.get("pid"))
PY

echo "Done."
