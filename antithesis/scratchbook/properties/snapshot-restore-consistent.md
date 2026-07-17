# snapshot-restore-consistent

**Side:** Workload-side safety net (WL) + optional SUT-side reachability for the restore path.

## Guarantee
After the Raft log is truncated to index N and a node restores from snapshot, its DB
state equals the leader's state at N; CRC catches corruption.

## Workload model
Force frequent snapshots (small `-raft-snap`). Crash / lag a node so it must catch up
via snapshot install rather than log replay, then let it rejoin. Assert that after it
rejoins, `no-replica-divergence` and `acked-write-survives-failover` still hold for it.
`Always` for the content-equality safety net. A `Reachable("node restored from
snapshot")` in `fsmRestore` proves the path was actually exercised.

## Code paths
- Snapshot: `fsmSnapshot` `store/store.go:2560+`, WAL checkpoint `synchronous=FULL`
  (~2581).
- Snapshot store is ground truth for state at N: `snapshot/DESIGN.md:7,37-52`.
- CRC integrity: `snapshot/crc_checker.go`, `snapshot/DESIGN.md:52`.
- Restore: `fsmRestore` `store/store.go:2760-2820`; resets `fsmIdx`/`dbAppliedIdx`/
  terms `2810-2818`.

## What breaks if violated
Snapshot install is how lagging/new nodes catch up; a bug corrupts a node's state with
no write ever being wrong — divergence introduced purely by recovery.

## Antithesis angle / timing
Crash + rejoin timing that forces snapshot-based catch-up rather than log replay.
Combine with disk-level corruption faults to exercise the CRC check.

## Open questions
- Confirming the node truly went through snapshot *install* (not log replay) needs an
  SUT-side `assert.Reachable` in `fsmRestore` (`store/store.go:2760`). Workload can
  only confirm the end state matches. (partial — SUT reachability optional but
  strengthens coverage.)
