#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd -- "${SKILL_DIR}/../../.." && pwd)"
VENV_DIR="${HOME}/.clawteam-venv"
LAUNCHER="${HOME}/.local/bin/clawteam"
PYTHON_BIN="${VENV_DIR}/bin/python"

mkdir -p "${HOME}/.local/bin"

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv is not installed or not on PATH." >&2
  exit 1
fi

uv venv "${VENV_DIR}"
(
  cd "${REPO_ROOT}"
  uv pip install --python "${PYTHON_BIN}" -e ".[dev]"
)

cat > "${LAUNCHER}" <<EOF
#!/usr/bin/env bash
exec ${PYTHON_BIN} -m clawteam.cli.commands "\$@"
EOF
chmod +x "${LAUNCHER}"

python - <<'PY'
from pathlib import Path

bashrc = Path.home() / ".bashrc"
launcher = Path.home() / ".clawteam-venv" / "bin" / "python"
block = f"""# >>> clawteam launcher >>>
clawteam() {{
  {launcher} -m clawteam.cli.commands "$@"
}}
# <<< clawteam launcher <<<
"""

text = bashrc.read_text() if bashrc.exists() else ""
start = "# >>> clawteam launcher >>>"
end = "# <<< clawteam launcher <<<"
if start in text and end in text:
    prefix = text.split(start, 1)[0]
    suffix = text.split(end, 1)[1]
    updated = prefix + block + suffix
else:
    updated = text.rstrip() + ("\n\n" if text.strip() else "") + block
bashrc.write_text(updated)
PY

echo "ClawTeam development environment is ready."
echo "Launcher: ${LAUNCHER}"
echo "Venv: ${VENV_DIR}"
echo "Next: source ~/.bashrc && clawteam --version"
