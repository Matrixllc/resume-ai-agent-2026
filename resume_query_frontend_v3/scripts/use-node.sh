#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
NODE_VERSION="$(tr -d '[:space:]' < "$PROJECT_DIR/.nvmrc")"

if [ -z "$NODE_VERSION" ]; then
  echo "Missing Node version in $PROJECT_DIR/.nvmrc" >&2
  exit 1
fi

if [ ! -s "$NVM_DIR/nvm.sh" ]; then
  echo "nvm was not found at $NVM_DIR/nvm.sh" >&2
  echo "Install nvm first, then rerun this script." >&2
  exit 1
fi

# shellcheck source=/dev/null
. "$NVM_DIR/nvm.sh"

echo "Using Node $NODE_VERSION for $PROJECT_DIR"
nvm install "$NODE_VERSION"
nvm use "$NODE_VERSION"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is missing after switching Node. Reinstalling Node with npm bundled..."
  nvm uninstall "$NODE_VERSION"
  nvm install "$NODE_VERSION"
  nvm use "$NODE_VERSION"
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is still missing after reinstalling Node." >&2
  exit 1
fi

NVM_BIN_DIR="$(dirname "$(command -v node)")"
NPM_BIN="$(command -v npm)"
if [ "$(dirname "$NPM_BIN")" != "$NVM_BIN_DIR" ]; then
  echo "npm is outside the active nvm Node ($NPM_BIN). Installing npm 10 into $NVM_BIN_DIR..."
  npm install -g npm@10
  hash -r 2>/dev/null || true
fi

NPM_VERSION="$(npm -v)"
echo "node: $(node -v) ($(command -v node))"
echo "npm:  $NPM_VERSION ($(command -v npm))"
echo
echo "Next steps:"
echo "  npm install"
echo "  npm run dev:local"
