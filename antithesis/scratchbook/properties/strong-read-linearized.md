# strong-read-linearized

**Side:** Workload-side (WL).

## Guarantee
A `strong` read reflects every write committed before the read entry — it is
trivially linearizable because it is processed by every FSM in log order.

## Workload model
After receiving a commit ack for version V of key K, issue a strong read of K and
assert the returned version `>= V`. `Always` on successful reads.

## Code paths
- Strong path: `store/store.go:1545-1583` — the read is marshaled as
  `COMMAND_TYPE_QUERY` and submitted via `raft.Apply` (`1569`).
- FSM handles the query in log order: `store/command_processor.go:52-58` (query,
  non-mutating).
- Guarantee statement: `store/DESIGN.md:44`.
- On success it also stamps `strongReadTerm` (`store/store.go:1580`), which is what
  the linearizable term-establishment check reads (see linearizable-upgrades-to-strong).

## What breaks if violated
Strong is the "most correct" reference read; staleness here means the log-ordered read
mechanism is broken, undermining every other read level's trust.

## Antithesis angle / timing
Failover during the strong read's `raft.Apply` yields `ErrNotLeader` /
`ErrLeadershipLost` (`store/store.go:1571-1573`); the workload retries on the new
leader. The eventual successful read must not be behind an earlier ack.

## Open questions
- Overlaps `linearizable-read-not-stale`; kept separate because it exercises the
  log-Apply path rather than the read-index path. Also serves as the reconciliation
  read for ledger-conservation. (partial)
