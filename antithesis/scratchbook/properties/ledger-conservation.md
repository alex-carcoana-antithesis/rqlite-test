# ledger-conservation

**Side:** Workload-side (WL).

## Guarantee
`SUM(balance)` over all accounts equals the seeded initial total at every observation.

## Workload model
Seed N accounts summing to `TOTAL`. A transfer op moves a random amount from account A
to account B as a bulk write (two statements, one Raft entry / one FSM apply):
`UPDATE accounts SET balance = balance - amt WHERE id=A AND balance >= amt;`
`UPDATE accounts SET balance = balance + amt WHERE id=B;`
Atomicity comes from both statements landing in a single `proto.Command`
(`COMMAND_TYPE_EXECUTE_QUERY` or a bulk execute), applied once by
`CommandProcessor.Process` (`store/command_processor.go:66-72`).

## Code paths
- Write ingress + rewrite: `http/service.go:1367` (execute), `1528` (request).
- Raft apply / single mutation point: `store/store.go:1706` (Request Apply),
  `store/command_processor.go:45-146`, `fsmApply` `store/store.go:2491-2553`.
- Reconciliation read: use `linearizable` (`store/store.go:1533`) for a consistent
  snapshot without injecting a read into the log.

## What breaks if violated
- A transfer applied on some replicas but not others (divergence) → sum differs by node.
- A transfer applied twice (retry after a leader change that already committed) →
  duplicated credit.
- A partially-applied bulk write (debit without credit) → sum drops.

## Antithesis angle / timing
Crash the leader between `raft.Apply` returning committed and the HTTP ack; partition
during quorum replication; kill a node mid-drain of a queued transfer. The invariant
must hold at every quiescent observation across all timelines.

## Open questions
- Reconciliation must read a *consistent* snapshot; a NONE read across accounts mid-
  transfer could observe a torn state even though the DB is fine. Use a single
  linearizable/strong read that returns all balances in one statement
  (`SELECT SUM(balance) FROM accounts`) so SQLite gives a consistent view.
