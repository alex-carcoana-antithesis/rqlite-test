# weak-read-staleness-bounded

**Side:** Workload-side (WL), with a leadership cross-check.

## Guarantee
A `weak` read is served only by a node that currently believes it is leader; a
partitioned ex-leader stops serving weak reads once it steps down, keeping weak
staleness within the documented bound.

## Workload model
Two-part check:
1. `AlwaysOrUnreachable(weak_read_version >= acked_version - slack)` — a weak read is
   at most `slack` behind the latest ack.
2. Any node returning weak data must report `is_leader` (cross-check against
   `/status`).
Companion `Sometimes(weak_stale_window_observed_then_recovered)` records the stale
window is actually reached without ever crossing the hard bound.

## Code paths
- Weak enforcement: `store/store.go:1585-1586` — if `raft.State() != raft.Leader`
  return `ErrNotLeader`. No quorum round-trip.
- Contrast with linearizable (`1533`) which does verify quorum.

## What breaks if violated
A deposed/partitioned leader keeps answering weak reads with arbitrarily old data
(zombie leader). Weak is the default level, so this is a broad exposure.

## Antithesis angle / timing
Partition the leader. There is a window between losing quorum contact and
`raft.State()` no longer returning `Leader`; a weak read in that window can be briefly
stale. Antithesis controls this timing precisely. The check confirms the ex-leader
stops serving once it steps down and the stale window never exceeds the bound.

## Open questions
- **(needs human input)** The exact staleness bound is not a literal in `Query`. It is
  governed by the Raft leader-lease / heartbeat timeout, not the "~1s" figure in
  CLAUDE.md. Why it matters: the `slack` constant in the assertion is unjustified
  without the real bound — too tight causes false positives, too loose misses real
  zombie-leader bugs. Need confirmation of whether a leader lease is in effect and its
  duration.
