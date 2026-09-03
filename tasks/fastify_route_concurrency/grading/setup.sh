#!/usr/bin/env bash
# Node 22 and the repo's dependencies (runs as root before the repo is handed
# to the agent; the same step the task's Dockerfile used to run).
set -euo pipefail
use-node 22
cd "$REPO_DIR"
npm install --no-audit --no-fund
