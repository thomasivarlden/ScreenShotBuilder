#!/usr/bin/env bash
# Screenshot Builder — Android emulator capture orchestrator launcher
# Drives the running emulator over adb to log into each brand's Flutter app
# and grab screenshots into assets/screenshots/<brand>/.
#
# Usage:
#   ./capture.sh --list                         # show configured brands/screens
#   ./capture.sh --list-avds                    # show installed AVDs
#   ./capture.sh --start-emulator               # boot first AVD if none running
#   ./capture.sh --brand fishy --screen home    # capture one (assumes emulator + APK ready)
#   ./capture.sh --start-emulator --brand fishy --screen home --rebuild

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="${SCRIPT_DIR}/.venv"
REQ_FILE="${SCRIPT_DIR}/requirements.txt"
APP_FILE="${SCRIPT_DIR}/capture.py"

color() { printf "\033[1;36m%s\033[0m\n" "$*"; }
fail()  { printf "\033[1;31m%s\033[0m\n" "$*" >&2; exit 1; }

# 1. python3
command -v python3 >/dev/null 2>&1 || fail "python3 is not installed or not on PATH."

# 2. adb (from the working SDK, not the broken Homebrew one)
if ! command -v adb >/dev/null 2>&1; then
  if [[ -x "$HOME/Library/Android/sdk/platform-tools/adb" ]]; then
    export PATH="$HOME/Library/Android/sdk/platform-tools:$PATH"
  else
    fail "adb not found. Install Android platform-tools or add ~/Library/Android/sdk/platform-tools to PATH."
  fi
fi

# 3. project files
[[ -f "$APP_FILE" ]] || fail "Missing capture script: $APP_FILE"
[[ -f "$REQ_FILE" ]] || fail "Missing requirements file: $REQ_FILE"

# 4. venv (shared with editor.sh / process.sh)
if [[ ! -d "$VENV_DIR" ]]; then
  color "  Creating virtual environment at .venv"
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

# 5. deps (only reinstall when requirements.txt changes)
HASH_FILE="${VENV_DIR}/.req.hash"
NEW_HASH="$(shasum -a 256 "$REQ_FILE" | awk '{print $1}')"
OLD_HASH="$(cat "$HASH_FILE" 2>/dev/null || true)"
if [[ "$NEW_HASH" != "$OLD_HASH" ]]; then
  color "  Installing dependencies"
  python -m pip install --quiet --upgrade pip
  python -m pip install --quiet -r "$REQ_FILE"
  echo "$NEW_HASH" > "$HASH_FILE"
fi

exec python "$APP_FILE" "$@"
