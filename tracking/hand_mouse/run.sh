#!/usr/bin/env bash
# Convenience launcher. Reuses the venv next door in dji_tracker/.
cd "$(dirname "$0")"
VENV="../dji_tracker/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "venv not found at $VENV — set up the dji_tracker venv first."
  exit 1
fi
exec "$VENV/bin/python" hand_mouse.py "$@"
