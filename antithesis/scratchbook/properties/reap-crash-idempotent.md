# reap-crash-idempotent

**Side:** Workload-side safety net (WL) + SUT-side reachability for meaningful coverage.

## Guarantee
A crash during snapshot reaping / log truncation recovers via idempotent plan replay
with no data loss.

## Workload model
Drive continuous writes so reaping happens often, crash nodes at random points, and
rely on `ledger-conservation` + `acked-write-survives-failover` as the safety net: no
acked write may vanish, and the sum must stay conserved, across any crash-mid-reap.
`Always` for the safety net. A `Reachable("reap resumed from persisted plan after
crash")` marker confirms the crash-mid-reap interleaving is actually hit.

## Code paths
- Reap is an idempotent, crash-safe plan replay: `snapshot/DESIGN.md:100,164`.
- Interacts with `fsmApply`'s snapshot invalidation on LOAD
  (`store/store.go:2543-2551`).

## What breaks if violated
Reaping mutates on-disk snapshot structure and truncates the log. A non-idempotent
crash recovery could truncate a log entry whose mutation the DB state doesn't yet
reflect → lost committed writes.

## Antithesis angle / timing
The reap window is short and internal; Antithesis can hit narrow timing windows across
branches by crashing precisely during reaping. Recovery must replay the plan and lose
nothing.

## Open questions
- **(needs human input)** Without an SUT-side reachability marker in the reap plan-
  replay path, we can only confirm conservation held, not that we actually hit the
  crash-mid-reap window. Why it matters: the safety net could pass simply because the
  window was never exercised — a reachability marker makes coverage meaningful. SUT
  source edit required.
