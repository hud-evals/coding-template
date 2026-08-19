You are working in the repository at /workspace/repo (Node 24, pnpm 10; dependencies are already installed and the toolchain works offline). Your shell has no network access, so the repo's connected test suite (which needs a live DynamoDB Local instance) cannot be run here — it will be run against DynamoDB Local when your change is reviewed, so keep it green by construction. Validate your work with the offline gates: the unit test suite (`pnpm vitest run` inside packages/effect-dynamodb), lint, and typecheck. Please resolve the following ticket:

## Aggregate listing doesn't scale

We drive our admin console's browse screens with `db.aggregates.X.list(filter, { limit, cursor })`. The console renders a single chronological feed — list-index sort-key order — fetching one page at a time. Two problems now that we have real data volume:

1. **Listing is slow, and latency grows linearly with page size.** A page of 50 aggregates takes several seconds. An SDK-level trace of one `list()` call shows the underlying DynamoDB queries executing strictly one after another.

2. **Sharded listing is broken.** On our highest-write aggregate we configured the sharded list index (`cardinality`) to spread write load. On that aggregate `list()` ignores `limit`, always comes back with `cursor: null`, and the feed arrives grouped rather than in feed order. From the caller's perspective, listing a sharded aggregate needs to behave exactly like listing an unsharded one: same paging behavior, same cursor contract, same ordering.

One ops note: these tables run on modest provisioned throughput and we've had throttling incidents before when a deploy fanned requests out too aggressively. Also, cursors already held by deployed clients must keep working.

All repo quality gates apply.
