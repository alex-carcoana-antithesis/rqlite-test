# queue-fifo-order

**Side:** Workload-side (WL) for the externally-visible guarantee; optional SUT-side for internal seq monotonicity.

## Guarantee
Queued writes commit in submission order: a lower queue sequence number commits before
a higher one.

## Workload model
For a key K, submit writes with strictly increasing versions v1 < v2 < v3 through
`?queue`. A later strong read of K must show a version consistent with submission
order — no inversion where a later-submitted-but-lower version overwrites a
higher one out of order. Combined with the versioned register's monotonicity check.
`Always`.

## Code paths
- `Queue.Write` returns a monotonically increasing seq and guarantees lower-seq batch
  is transmitted before higher-seq on the queue's output channel
  (`queue/queue.go:122-126`, `132`).
- HTTP queued path: `http/service.go:1279-1337` (`queuedExecute`).
- Drain: `runQueue` `http/service.go:1740-1799` — reads batches in order, calls
  `proxy.Execute`, retries forever.

## What breaks if violated
Out-of-order application of queued writes corrupts any order-dependent workload and
breaks the register's monotonic-version guarantee.

## Antithesis angle / timing
Crash / leader-change during the drain loop: does the retry-forever resubmission
preserve batch order, or can a retried batch land after a later one?

## Open questions
- Workload observation proves *committed* order, not that the queue channel never
  reorders internally. A tighter check would add an SUT-side `assert.Always(seq
  monotonic)` in `runQueue`. Workload-side is sufficient for the externally-visible
  contract; note the SUT option. (partial)
- Multiple keys interleave; assert per-key monotonicity, not a global order. (partial)
