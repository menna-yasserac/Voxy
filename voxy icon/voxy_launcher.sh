#!/usr/bin/env bash
# Launches Voxy.
# - Loads GROQ_API_KEY from ~/.config/voxy/voxy.env (menu-launched apps do not
#   see variables from your shell).
# - Uses the project's virtual environment automatically if one exists
#   (venv/, .venv/ or env/ next to this file), otherwise system python3.
#   You can force a specific python with VOXY_PYTHON=/path/to/python in voxy.env.
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
ENV_FILE="$HOME/.config/voxy/voxy.env"
if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
fi

PY="${VOXY_PYTHON:-}"
if [ -z "$PY" ]; then
  for v in venv .venv env; do
    if [ -x "$DIR/$v/bin/python" ]; then PY="$DIR/$v/bin/python"; break; fi
  done
fi
PY="${PY:-python3}"

cd "$DIR"
exec "$PY" "$DIR/voxy_gui_test.py" "$@"
