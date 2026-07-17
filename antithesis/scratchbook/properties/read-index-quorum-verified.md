# read-index-quorum-verified

**Side:** SUT-side (surgical SDK assertion in `store/store.go`). REQUIRES SUT SOURCE EDIT.

## Guarantee
The linearizable read path actually executes the `VerifyLeader` quorum heartbeat
round-trip before serving a result.

## Why it must be SUT-side
Whether `VerifyLeader` actually ran (vs being short-circuited or cached) is invisible
to a client. Only an in-process `assert.Reachable` placed after a successful
`VerifyLeader()` can confirm the mechanism fired.

## Where the assertion goes
- `store/store.go:2441-2443` — immediately after `VerifyLeader()` returns nil in
  `waitForLinearizableRead`, ideally gated on the read then succeeding.

## Code paths
- Read-index technique: `readIndex := s.raft.CommitIndex()` (`2440`),
  `VerifyLeader()` (`2441`, impl `1596-1618`), term-stability check (`2444-2445`),
  wait for FSM (`2453-2458`).
- Raft dissertation §6.4, referenced in the code comment (`2438-2439`).

## What breaks if violated
If `VerifyLeader` were skipped (e.g. a caching regression), linearizable reads would
silently degrade to weak-level reads — correct-looking most of the time, wrong under a
partition. This property proves the quorum step runs.

## Antithesis angle / timing
Under both healthy and post-partition conditions the read must still perform the
quorum verification. Pairs with `linearizable-read-not-stale` (which checks the
outcome) to also confirm the mechanism.

## Open questions
- **(needs human input)** SUT source edit + SDK dependency in the SUT build.
- Could partially overlap `linearizable-upgrades-to-strong`; keep both since they mark
  distinct branches (upgrade vs verified-and-served). (partial)
