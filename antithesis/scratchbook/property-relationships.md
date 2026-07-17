---
sut_path: /Users/alexcarcoana/Desktop/rqlite
commit: 28a7a521174dc4c2e4334b6ee552809c9567f030
updated: 2026-07-06
external_references: []
---

# Property Relationships

Clusters, dominance relations, and connections among the 18 cataloged properties.
Every slug below exists in `property-catalog.md`.

## Cluster 1 — Replicated-state determinism (the foundation)

- `no-replica-divergence` (root safety)
- `nondeterministic-rewrite-identical` (a specific *cause* of divergence)
- `single-leader` (a specific *cause* of divergence: two leaders → two logs)

**Dominance:** `no-replica-divergence` is the broadest detector — almost any consensus
bug eventually shows up as two nodes at the same index with different content.
`nondeterministic-rewrite-identical` and `single-leader` are narrower, root-cause
detectors that pinpoint *why* divergence happened. If `single-leader` or
`nondeterministic-rewrite-identical` fails, expect `no-replica-divergence` to fail too
— they localize the blame.

## Cluster 2 — Durability & atomicity of writes

- `ledger-conservation` (atomic, exactly-once transfers)
- `no-negative-balance` (conditional-write isolation)
- `acked-write-survives-failover` (committed = durable)

**Connections:** `ledger-conservation` is a superset alarm for `acked-write-survives-
failover` — a lost acked transfer breaks conservation *and* durability. `no-negative-
balance` is orthogonal: it catches stale-read-feeds-write even when the sum stays
conserved. All three share the same write/apply path (`store/store.go:1706`,
`command_processor.go:45-146`).

## Cluster 3 — Read-consistency ladder

- `strong-read-linearized` (strongest; reference oracle)
- `linearizable-read-not-stale` (read-index path)
- `weak-read-staleness-bounded` (leader-local, bounded staleness)
- `none-read-freshness-honored` (explicit freshness bound)
- `linearizable-upgrades-to-strong` (SUT) — mechanism inside linearizable
- `read-index-quorum-verified` (SUT) — mechanism inside linearizable

**Dominance / structure:** these form a strict correctness ladder
strong ≥ linearizable ≥ weak ≥ none. `strong-read-linearized` and
`linearizable-read-not-stale` assert the *outcome* (no stale value); the two SUT
properties assert the *mechanism* that produces that outcome (the term-establishment
upgrade and the quorum verify). The mechanism properties are only meaningful if the
outcome properties also hold — they explain *how* linearizability is achieved and give
coverage credit for exercising the corner cases. `weak` and `none` deliberately relax
the guarantee, so their properties bound the relaxation rather than forbid staleness.

## Cluster 4 — Control-plane liveness

- `single-leader` (safety — also in Cluster 1)
- `leader-elected-after-crash` (liveness)

**Connection:** `single-leader` (at most one) and `leader-elected-after-crash` (at
least one, eventually) are the two halves of Raft's leader guarantee — one is safety,
one is liveness. `single-leader` bridges into Cluster 1 because split brain is the
worst divergence cause.

## Cluster 5 — Write-path ordering & fault liveness

- `queue-fifo-order` (ordering safety)
- `progress-under-fault` (liveness)
- `write-eventually-commits` (liveness of the queued drain specifically)

**Connections:** `write-eventually-commits` is a narrower, queue-specific instance of
`progress-under-fault`. `queue-fifo-order` is the safety companion to both liveness
properties — the drain must not just make progress, it must preserve order. All three
center on `http/service.go:1740-1799` (`runQueue`).

## Cluster 6 — Snapshot / recovery correctness

- `snapshot-restore-consistent` (safety; content match after restore)
- `reap-crash-idempotent` (safety; no loss on crash-mid-reap)

**Dominance:** both fall back on Cluster-1/2 oracles (`no-replica-divergence`,
`acked-write-survives-failover`, `ledger-conservation`) as their safety net. Their own
value is the *reachability* of the snapshot-install and reap-crash paths — without the
SUT-side reachability markers, a green run may simply mean those narrow paths were
never exercised.

## Cross-cluster dominance summary

- **Broadest alarms** (fail loudly on almost any bug): `no-replica-divergence`,
  `ledger-conservation`, `acked-write-survives-failover`.
- **Root-cause localizers** (explain *why*): `single-leader`,
  `nondeterministic-rewrite-identical`, `queue-fifo-order`.
- **Mechanism / coverage markers** (SUT-side, prove the corner was hit):
  `linearizable-upgrades-to-strong`, `read-index-quorum-verified`,
  `snapshot-restore-consistent` (reachability part), `reap-crash-idempotent`
  (reachability part).
- **Liveness backbone**: `leader-elected-after-crash`, `progress-under-fault`,
  `write-eventually-commits`.

If forced to prioritize a minimal high-signal set: `no-replica-divergence`,
`ledger-conservation`, `acked-write-survives-failover`, `single-leader`,
`linearizable-read-not-stale`, plus `leader-elected-after-crash` for liveness. The
remaining properties add localization and coverage of specific mechanisms.

## External references
(none — repo only)
