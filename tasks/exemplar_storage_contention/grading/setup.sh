#!/usr/bin/env bash
# Toolchain and warm caches for the agent's workspace (runs as root before the
# repo is handed over; the same steps the task's Dockerfile used to run).
set -euo pipefail
use-go 1.25
cd "$REPO_DIR"
go mod download
go build ./tsdb/...
go test -count=1 -run XXX_NONE ./tsdb/
go test -race -count=1 -run XXX_NONE ./tsdb/
