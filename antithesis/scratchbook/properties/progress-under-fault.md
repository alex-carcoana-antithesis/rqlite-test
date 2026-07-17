# progress-under-fault

**Side:** Workload-side (WL).

## Guarantee
A write is eventually acknowledged even while fault injection (partition/crash of a
minority) is active or recently active — fault-tolerant availability.

## Workload model
While a minority-affecting fault is active (one node down/partitioned, quorum
surviving), keep driving writes and assert `Sometimes(write_acked)` — at least one
write commits during or shortly after the fault. Record fault-active timestamp vs ack
time to know whether the ack landed during vs after the fault.
`Sometimes(write_acked_during_or_after_fault)`.

## Code paths
- Standard write commit path: `store/store.go:1447-1499`, `1677-1710`.
- Queued retry-forever drain: `http/service.go:1740-1799` (`runQueue` retries through
  `proxy.Execute` until commit).

## What breaks if violated
A cluster that only makes progress in perfectly healthy conditions is useless; this
proves it commits writes while tolerating a minority failure.

## Antithesis angle / timing
Keep a minority node down/partitioned while driving writes. Leader stability under
minority fault + the queued retry path must still commit. Antithesis explores exactly
when writes are submitted relative to the fault window.

## Open questions
- "Acked during fault" (stronger) vs "acked after heal" (weaker); both prove liveness.
  Record timestamps to distinguish. (partial)
- Scope the `Sometimes` to quorum-survivable timelines; a majority-loss timeline
  correctly makes no progress. (partial)
