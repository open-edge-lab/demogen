#!/usr/bin/env sh
# Menu di demogen su macOS/Linux: lanciatore Node + TypeScript in scripts/run.mts (oppure: npm run menu)
exec node "$(dirname "$0")/scripts/run.mts" "$@"
