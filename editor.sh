#!/usr/bin/env bash
# Screenshot Builder — GUI corner editor launcher
# (C) Thomas F Abrahamsson at Alvega & Co AB <Thomas@alvega.company>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="${SCRIPT_DIR}/.venv"
REQ_FILE="${SCRIPT_DIR}/requirements.txt"
APP_FILE="${SCRIPT_DIR}/editor.py"

color() { printf "\033[1;36m%s\033[0m\n" "$*"; }
warn()  { printf "\033[1;33m%s\033[0m\n" "$*" >&2; }
fail()  { printf "\033[1;31m%s\033[0m\n" "$*" >&2; exit 1; }

color "Screenshot Builder — GUI editor startup"

# 1. Python 3.10+
command -v python3 >/dev/null 2>&1 || fail "python3 is not installed or not on PATH."
PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_OK="$(python3 -c 'import sys; print(1 if sys.version_info >= (3,10) else 0)')"
[[ "$PY_OK" == "1" ]] || fail "Python >= 3.10 required (found ${PY_VER})."
color "  python3 ${PY_VER} OK"

# 2. tkinter
if ! python3 -c "import tkinter" >/dev/null 2>&1; then
  cat >&2 <<EOF
Tkinter is not available in your Python.

  macOS (Homebrew): brew install python-tk@${PY_VER}
  Ubuntu/Debian   : sudo apt install python3-tk
  Fedora          : sudo dnf install python3-tkinter

Tkinter is a standard library module but is sometimes packaged
separately. Install the matching package and re-run editor.sh.
EOF
  exit 1
fi
color "  tkinter OK"

# 3. Project files
[[ -f "$APP_FILE" ]] || fail "Missing editor file: $APP_FILE"
[[ -f "$REQ_FILE" ]] || fail "Missing requirements file: $REQ_FILE"
[[ -d "${SCRIPT_DIR}/include" ]] || fail "Missing include/ folder."

# 4. venv
if [[ ! -d "$VENV_DIR" ]]; then
  color "  Creating virtual environment at .venv"
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

# 5. Install / upgrade deps (only if requirements changed)
HASH_FILE="${VENV_DIR}/.req.hash"
NEW_HASH="$(shasum -a 256 "$REQ_FILE" | awk '{print $1}')"
OLD_HASH="$(cat "$HASH_FILE" 2>/dev/null || true)"
if [[ "$NEW_HASH" != "$OLD_HASH" ]]; then
  color "  Installing dependencies"
  python -m pip install --quiet --upgrade pip
  python -m pip install --quiet -r "$REQ_FILE"
  echo "$NEW_HASH" > "$HASH_FILE"
else
  color "  Dependencies up to date"
fi

color "Launching editor..."
exec python "$APP_FILE" "$@"
