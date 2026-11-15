#!/bin/sh
set -eu
cd "$(dirname "$0")"

# Use an installed Node.js first, then the runtime bundled with Codex on this Mac.
if command -v node >/dev/null 2>&1; then
  node_bin="$(command -v node)"
else
  node_bin="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
fi

if [ ! -x "$node_bin" ]; then
  echo "Install Node.js 20.9 or newer, then run this script again."
  exit 1
fi
if [ ! -f node_modules/next/dist/bin/next ]; then
  echo "Install the project dependencies with pnpm install, then run this script again."
  exit 1
fi
export PATH="$(dirname "$node_bin"):$PATH"
export NEXT_TELEMETRY_DISABLED=1
exec "$node_bin" node_modules/next/dist/bin/next dev --hostname 127.0.0.1
