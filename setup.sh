#!/usr/bin/env bash
# Linux/macOS: bash setup.sh [--openclaw setup] [--no-launch]
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
for candidate in python3.12 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys,venv;sys.exit(sys.version_info < (3,12))' 2>/dev/null; then
    exec "$candidate" setup.py "$@"
  fi
done
uv_bin="$(command -v uv || true)"
if [ -z "$uv_bin" ]; then
  uv_bin="$HOME/.local/bin/uv"
  if [ ! -x "$uv_bin" ]; then
    installer="$(mktemp)"
    trap 'rm -f "$installer"' EXIT
    if command -v curl >/dev/null 2>&1; then
      curl --fail --location --proto '=https' --tlsv1.2 https://astral.sh/uv/install.sh -o "$installer"
    elif command -v wget >/dev/null 2>&1; then
      wget -q https://astral.sh/uv/install.sh -O "$installer"
    else
      echo 'Install curl or wget using your OS package manager, then rerun.' >&2
      exit 1
    fi
    UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 sh "$installer"
  fi
fi
"$uv_bin" python install 3.12
exec "$uv_bin" run --no-project --python 3.12 setup.py "$@"
