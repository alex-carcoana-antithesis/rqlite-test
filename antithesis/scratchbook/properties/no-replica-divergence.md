# no-replica-divergence

**Side:** Workload-side (WL), compared across all nodes at quiescence.

## Guarantee
Any two replicas that have applied the same Raft index produce byte-identical DB
content. Also validates that non-deterministic rewriting produced identical literals
on every node.

## Workload model
At a quiescent point (no writes in flight), the workload reads from each node:
- its applied index (via `/status`), and
- a content hash: e.g. `SELECT` all rows in a canonical order and hash, or per-table
  `SELECT count(*), SUM(...)` fingerprints.
Only nodes reporting the **same** applied index are compared; equal index ⇒ equal
hash is asserted. `Always`.

## Code paths
- Determinism source: single mutation point `store/command_processor.go:45-146`,
  `fsmApply` `store/store.go:2491-2553` — same log, same order, same commands.
- Non-deterministic rewriting (so RANDOM/time are identical): `command/sql/processor.go:43-78`,
  visitor `171-199`; ingress rewrite `http/service.go:1305/1367/1452/1528`.
- Applied-index accounting: `fsmIdx` / `dbAppliedIdx` in `fsmApply`.

## What breaks if violated
Silent divergence: two nodes at the same index return different data. Sources: an
unrewritten non-deterministic function, non-deterministic collation/ordering, a
missing `LOAD` snapshot/CDC invalidation (`store/store.go:2543-2551`), or an
apply-order bug.

## Antithesis angle / timing
Message reorder, partition-heal, crash-restart all perturb apply *timing* but must not
perturb apply *result*. Comparing same-index hashes across nodes is the direct
divergence detector.

## Open questions
- Reading each node's index and hash is not perfectly atomic; mitigate by only
  comparing node pairs that report an identical index, retrying until a match is
  found at quiescence. (partial)
- Choosing a hash that is itself deterministic across SQLite versions — order rows
  explicitly by primary key. (partial)
