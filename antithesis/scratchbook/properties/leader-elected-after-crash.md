# leader-elected-after-crash

**Side:** Workload-side (WL) — or SUT-side observable via /status.

## Guarantee
After the current leader is crashed or partitioned away, a surviving follower becomes
leader (election liveness).

## Workload model
Record the current leader id; wait out a fault that removes it (crash or partition of
the leader) while a quorum (2 of 3) survives; assert a *different* node eventually
reports leader. `Sometimes(new_leader_elected_after_prior_leader_lost)`.

## Code paths
- Elections handled by `hashicorp/raft`; leadership observable via `/status` and
  `Node.wait_for_leader` (`system_test/e2e/helpers.py`).
- Bootstrap/rejoin: `cmd/rqlited/main.go:583-653`.

## What breaks if violated
If elections stall while a quorum survives, the cluster is unavailable for writes —
the baseline liveness failure.

## Antithesis angle / timing
Directly exercises election liveness across the crash/partition faults Antithesis
injects, over branching timelines. The `Sometimes` proves re-election happens in at
least one quorum-survivable timeline.

## Open questions
- Only holds when a majority survives; the workload must **not** assert re-election in
  timelines where it partitioned away the majority (no quorum → correctly no leader).
  Gate the `Sometimes` on quorum-survivable faults. (partial)
