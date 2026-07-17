# single-leader

**Side:** Workload-side (WL), cross-node.

## Guarantee
No two nodes simultaneously report leadership in the same term (no split brain).

## Workload model
Poll all three nodes' `/status`; assert at most one reports `is_leader` **in the same
term**. Reuse `Cluster.cross_check_leader` (`system_test/e2e/helpers.py:713`) and the
`Node.is_leader` probe (`helpers.py:93`). `Always`.

## Code paths
- Leadership state comes from `hashicorp/raft`; `VerifyLeader`
  (`store/store.go:1596-1618`) is the quorum probe.
- `/status` exposes leader/term via the HTTP status handler.

## What breaks if violated
Two same-term leaders both accept writes → divergent logs → ledger and register
invariants both break. This is the upstream root-cause detector for divergence.

## Antithesis angle / timing
Asymmetric partitions, partition-heal races, and clock skew stress the election /
leader-lease logic. The dangerous case is two nodes claiming leader in the **same
term**; different terms sampled across real-time skew is benign.

## Open questions
- Include the term in the cross-check to avoid false positives from sampling skew: two
  leaders in different terms is a normal transition. (partial)
- `/status` sampling is not simultaneous across nodes; a brief cross-term overlap can
  appear. Comparing term makes this robust. (partial)
