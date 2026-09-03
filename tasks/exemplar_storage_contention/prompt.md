You are working in the Prometheus repository checked out at `/workspace/repo`.

Implement the change directly in that working tree — your uncommitted edits are the deliverable, so leave them in place rather than committing, stashing or reverting them. Hidden tests grade your work; do not modify or delete existing tests. Build and test with the Go toolchain already installed in the image (`go build ./tsdb/...`, `go test ./tsdb/ -run ...`).

Do not finish until you have actually changed the code: `git diff` in that repo must be non-empty, `go build ./tsdb/...` must succeed, and the exemplar tests must pass. Exploring the code and describing a plan is not a deliverable — an unmodified working tree scores zero.

Here is the ticket.

---

Exemplar ingestion is a bottleneck on our larger Prometheus servers.

At ~2000 scrape targets we see scrape loops backing up, and profiles put a lot of time parked in `CircularExemplarStorage` (`tsdb/exemplar.go`). Every exemplar append takes a storage-wide write lock, so all scrapers serialise against each other — and against anything that walks the storage, such as the chunk-snapshot writer.

Please make exemplar appends for different series stop blocking each other. This is a throughput ticket: the point is more total exemplar ingestion on many-core servers. Our fleet runs the production default `max_exemplars: 100000`, so that is the operating point that matters.

Acceptance on performance (measured on the storage in isolation, steady state, appenders on disjoint series, at the production default capacity):

- With ~8 cores appending in parallel we need clearly positive scaling — at least ~1.5x the throughput of a single appender on the same build, and honestly we expect much better. Today parallel is *slower* than serial, which is the whole complaint.
- Uncontended cost stays honest: a single appender must keep at least ~80% of its current throughput. Most of our fleet is small servers; buying parallelism by making every append slower would make things worse for them.
- The steady-state append path (an in-order exemplar for a series the storage already knows) must not allocate on the heap. The current code does not, and on a busy server every allocation is paid for by every goroutine in the process, not just the appender.
- Memory stays proportional to `max_exemplars`: after config reloads that shrink, grow, disable and re-enable the storage while appends are running, the storage must not be holding on to old buffers, generations or per-append bookkeeping. Concretely, a full 100000-exemplar storage must keep well under 50 MB of heap alive.
- Memory per stored exemplar — and per series — stays close to today's: for the same stored content the new storage may keep at most about 25% more heap alive than the current implementation does. We measure that the same way for the shapes we actually run at `max_exemplars: 100000`: a steady mix of a couple of thousand series, a storage full of quiet series holding one exemplar each (that is what most of the fleet looks like, so per-series bookkeeping is the whole bill there), the hot/cold skew described below, and the state after a reload storm has settled. Every exemplar carries its own labels (trace ids are unique), so an exemplar you no longer store but have not reclaimed yet counts against you, and so do padded entries or a large per-series record kept next to the index entry.

What has to keep working:

- A series' exemplars must still come back in the order they were ingested.
- `max_exemplars` must remain a hard upper bound on how much we retain — and the budget must remain usable: after sustained ingestion the storage should actually hold approximately what was configured (a few percent of internal slack is fine).
- Eviction stays global. When the buffer is full, the exemplar that goes is the oldest one in the whole storage, whichever series it belongs to, so that after sustained ingestion the storage holds the most recent `max_exemplars` exemplars ingested — approximately: we can live with ~10% of slack, not more. That is what the circular buffer promises today and what `prometheus_tsdb_exemplar_last_exemplars_timestamp_seconds` reports. Our targets are extremely uneven — a handful of hot services produce ~98% of all exemplars, thousands of quiet ones produce the rest — and a design that carves the buffer into fixed partitions of series is not acceptable: the partition holding a hot service would evict exemplars from a minute ago while the partitions holding only quiet services keep exemplars from an hour ago, or sit mostly empty. Either way most of the configured budget is wasted.
- Appends must not stall behind a walk of the storage, and that has to hold when a config reload arrives *while* the walk is running: the chunk-snapshot writer walks the storage slowly (it does real work per exemplar), reloads happen whenever an operator pushes one, and a scraper must not wait for the walk to finish in the meantime. Be careful with a storage-wide reader/writer lock here — once a reload is queued on its write side, every later reader is parked behind it until the walk is over, including an append that only touches that lock to refresh a gauge every few thousand exemplars.
- `IterateExemplars` must keep its documented contract: every stored exemplar, oldest to newest **in ingestion order across the whole storage**. The chunk-snapshot writer persists exemplars in that order, and on restart the WAL/snapshot replay feeds them back through `AddExemplar` in that same order. We resize servers at restart often enough that this is not theoretical: a snapshot replayed into a *smaller* buffer must come back holding the newest exemplars, not an arbitrary subset determined by your internal layout. And a snapshot written by a `Head` at the production default capacity and replayed on restart into the same capacity must come back in the same order: nothing reordered, duplicated or invented (dropping some of the oldest ones on the way in is tolerable).
- Ingestion order has to be real ingestion order, also when the *same* series is appended from several goroutines at once (remote-write receivers and OTLP ingestion do this), with some of those appends rejected as out of order. Any append that completed before another started is older than it, and a series' exemplars appear in the walk in the order they were accepted. An append that reserves its place in the storage before it is finally accepted or rejected, and cannot give that place back, will get this wrong.
- The existing test suite has to stay green. Some of it pins behaviour you might not expect to be load-bearing; if something there fails, treat it as a requirement to satisfy, not a test to rewrite.
- It must be clean under `-race` with realistic concurrency: appends across many series (including contended appends to the same series) while a config reload resizes the buffer (including through the disabled state and back) and queries and full walks run alongside. We have been bitten before by a change that was green on a plain `go test` and fell apart under load — expect us to hammer it at production capacity for a while.
- Add tests in the tsdb package's style for the concurrency behaviour you introduce; they must be clean under `-race`.
- Keep this to the tsdb package and leave CHANGELOG.md alone; release notes are written at release time.

Trade-offs we accept:

- A small additional per-append cost when uncontended (within the ~80% bound above), and some extra memory per stored exemplar (within the ~25% bound above).
- Queries no longer being a perfectly consistent point-in-time snapshot across all series is fine.
- The storage-level gauges (`prometheus_tsdb_exemplar_exemplars_in_storage` and friends) may lag ingestion by a bounded amount; per-append exactness is not required.
