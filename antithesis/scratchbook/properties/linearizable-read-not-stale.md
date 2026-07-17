# linearizable-read-not-stale

**Side:** Workload-side (WL), versioned register.

## Guarantee
A successful `linearizable` or `strong` read never returns a per-key version older
than a value the client previously received a committed ack for.

## Workload model
Per key K, maintain `max_acked[K]` = highest version the workload got a commit ack
for. Any successful linearizable/strong read of K asserts `read_version >=
max_acked[K]`. Error responses (`ErrStaleRead`, `ErrNotLeader`) are ignored — the
guarantee is about *successful* reads. `Always`.

## Code paths
- Linearizable enforcement: `store/store.go:1533-1543` → `waitForLinearizableRead`
  `2412-2460`.
- Term-change guard: `2444-2445` returns `ErrStaleRead` if the term changed during
  `VerifyLeader`.
- Quorum verify: `2440-2443` (`VerifyLeader` `1596-1618`).
- Wait for FSM to reach read index: `2453-2458`.
- Guarantee statement: `store/DESIGN.md:43`.

## What breaks if violated
A client reads its own committed write and gets an older value — read-after-write
violation, the central linearizability promise.

## Antithesis angle / timing
Trigger a leader change *during* a linearizable read so `VerifyLeader` runs while
leadership/term is shifting. The `2444-2445` term-change branch and the read-index
wait must prevent returning a value from before the leader established its term.

## Open questions
- Ensure the oracle only asserts on successful reads; a legitimate `ErrStaleRead`
  mid-election is correct behavior, not a violation. (partial)
- `strong` reads share this invariant but exercise a different path — see
  strong-read-linearized.
