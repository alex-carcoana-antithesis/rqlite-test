# none-read-freshness-honored

**Side:** Workload-side (WL).

## Guarantee
A `none`-level read with a `freshness` bound returns `ErrStaleRead` rather than data
staler than the bound.

## Workload model
Against a follower that has been partitioned from the leader, issue NONE reads with a
tight `freshness`. Assert: either the returned data is within the freshness bound, or
the call errored with `ErrStaleRead`. `Always`.

## Code paths
- NONE + freshness check: `store/store.go:1588` (Query) / `1666` (Request) →
  `isStaleRead` `2462-2474`.
- `isStaleRead` returns false if this node is leader; otherwise delegates to
  `IsStaleRead(raft.LastContact(), fsmUpdateTime, appendedAtTime, fsmIdx,
  CommandCommitIndex(), freshness, strict)`.
- Freshness/strict parse: `http/query_params.go` (freshness params).

## What breaks if violated
`none`+`freshness` is the latency-sensitive user's staleness bound; if a stale
follower serves data past the bound without erroring, the contract silently fails.

## Antithesis angle / timing
Partition a follower so `raft.LastContact()` ages past the freshness bound; the read
must flip from returning data to returning `ErrStaleRead`. Antithesis controls exactly
how long the partition lasts relative to the bound.

## Open questions
- `FreshnessStrict` changes the computation (also considers whether a write is in
  flight / commit index vs applied index). Test both strict and non-strict. (partial)
- Confirm the units of `freshness` (nanoseconds in the proto) match what the workload
  sends. (partial)
