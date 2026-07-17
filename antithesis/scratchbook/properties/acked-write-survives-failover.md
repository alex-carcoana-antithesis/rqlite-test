# acked-write-survives-failover

**Side:** Workload-side (WL).

## Guarantee
A write acknowledged as committed to the client is never lost after leader failover or
crash-restart.

## Workload model
Record every committed ack (register version / ledger transfer). After any fault +
recovery, re-read (strong) and assert every acked value is still present and `>=` the
acked version. `Always`.

Crucially, only treat **true-commit acks** as promises: standard writes (blocking
`raft.Apply` returned committed) and queued `wait=true` acks. A queued `wait=false`
response only means *enqueued*, not durable — must not be tracked as a promise.

## Code paths
- Standard write commit: `store/store.go:1447-1499` (Execute), `1677-1710` (Request),
  `raft.Apply` at `1706` blocks until committed.
- Queued wait=true: flush channel closes when applied (`http/service.go:1761-1792`).
- Durability rests on Raft: a committed entry replicated to a quorum survives any
  minority failure.

## What breaks if violated
"I got OK and my data vanished" — the highest-severity durability bug.

## Antithesis angle / timing
Crash the leader immediately after ack; partition-then-heal; crash-restart a node.
The committed entry must have replicated to the quorum and survive. Tests that a
standard ack really means durably committed, not merely locally applied.

## Open questions
- Distinguish standard/wait=true acks (durable) from queued wait=false (not durable);
  the oracle must only track the former. (partial)
