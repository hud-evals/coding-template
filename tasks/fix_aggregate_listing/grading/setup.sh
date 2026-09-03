#!/usr/bin/env bash
# Dependencies and builds the agent's workspace needs (runs as root, before the
# repo is handed to the agent; the same steps the task's Dockerfile used to run).
set -euo pipefail
use-node 24
cd "$REPO_DIR"
pnpm install --frozen-lockfile
pnpm --filter @effect-dynamodb/schema build
pnpm --filter effect-dynamodb build
pnpm --filter @effect-dynamodb/geo build
