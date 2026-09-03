#!/usr/bin/env bash
# Go 1.26 toolchain, module download and warm build caches (runs as root before
# the repo is handed to the agent; the steps the task's Dockerfile used to run).
set -euo pipefail
use-go 1.26
export GOTOOLCHAIN=local CGO_ENABLED=1 GOWORK=off GOFLAGS=-mod=mod
cd "$REPO_DIR"
go mod download all
go build ./...
go vet ./... || true
go test -count=1 -run XXXNONE ./db/... ./http/... ./command/... ./cmd/... ./store/ >/dev/null
