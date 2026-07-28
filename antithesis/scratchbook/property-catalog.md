---
sut_path: /Users/alexcarcoana/Desktop/rqlite
commit: 242b9d7f12e78b32d528e884a0f3c1a2d7469681
updated: 2026-07-21
external_references: []
---

# Property Catalog — rqlite Consensus & Read Consistency

Scope: core consensus + read-consistency correctness. Workload model: a
conserved-sum **ledger** (accounts, random transfers, `SUM(balance)` constant) plus a
per-key **versioned register** (monotonically increasing version per key). Topology:
3 voter nodes + 1 workload/driver container.

Assertion-type convention: `Always`/`AlwaysOrUnreachable` = safety invariants;
`Sometimes(cond)` = liveness / meaningful state reached at least once (never
`Sometimes(true)`); `Reachable`/`Unreachable` = path/outcome reachability.

Legend: **WL** = checkable purely workload-side by the oracle; **SUT** = needs a
surgical SDK assertion inside `store/store.go` (SUT source change).

---

## Category A — Data integrity under faults

### [ledger-conservation] — Conserved ledger sum

| | |
|---|---|
| **Type** | Safety |
| **Property** | `SUM(balance)` across all accounts always equals the seeded initial total, regardless of faults. |
| **Invariant** | `Always(sum == seeded_total)` (WL). The workload periodically reads all balances (using a strong/linearizable read for a consistent snapshot) and asserts equality with the constant seed total. `Always` matches because conservation is a hard invariant that must hold at every observation — any lost, duplicated, or partially-applied transfer breaks it. |
| **Antithesis Angle** | Transfers are two-statement bulk writes; partitions/crashes during `raft.Apply` and leader failover during a queued drain probe whether a transfer is applied atomically and exactly once across replicas. |
| **Why It Matters** | Money/inventory-style invariants are the canonical "did the database silently lose or duplicate a write" detector. |

**Open Questions:**
- Should the reconciliation read be `strong` (goes through the log) or `linearizable`? Strong gives a serialized snapshot but perturbs the log. `(partial: prefer linearizable to avoid injecting reads into the log; revisit if flakiness appears.)`

### [no-negative-balance] — No account goes negative

| | |
|---|---|
| **Type** | Safety |
| **Property** | No account balance is ever observed below zero. |
| **Invariant** | `AlwaysOrUnreachable(balance >= 0)` (WL). The debit side of a transfer must be guarded (`UPDATE ... WHERE balance >= amount`); the assertion fires on every balance read. `AlwaysOrUnreachable` (not plain `Always`) because a workload may, in some timelines, never drive a debit that would test the guard — we don't want to demand the state be reached, only that it never violates. |
| **Antithesis Angle** | Concurrent transfers racing on the same account under leader churn probe whether the conditional debit is evaluated against a consistent, committed balance rather than a stale local read. |
| **Why It Matters** | Guards conditional writes; a violation means a stale read fed a mutation, i.e. lost isolation. |

**Open Questions:**
- None.

### [no-replica-divergence] — Replicas at equal applied index are byte-identical

| | |
|---|---|
| **Type** | Safety |
| **Property** | Any two replicas that have applied the same Raft index produce identical DB content (hash of all table rows); this also validates that `RANDOM()`/`datetime('now')` rewriting yields the same literal on every node. |
| **Invariant** | `Always(hash_i == hash_j)` at quiescence (WL). At a quiescent point the workload reads each node's applied index and a content hash (e.g. `SELECT` ordered rows → hash) and asserts all nodes at equal index have equal hash. `Always` because determinism of the replicated state machine is the foundational Raft guarantee. |
| **Antithesis Angle** | Message reorder, partition-heal, and crash-restart force divergent apply timing; the check catches any non-deterministic apply (unrewritten RANDOM/time, non-deterministic collation, uninitialized column defaults). |
| **Why It Matters** | Silent replica divergence is the worst class of distributed-DB bug — reads return different answers depending on which node you hit. |

**Open Questions:**
- Comparing at *equal applied index* requires reading each node's index and content atomically-ish; small skew is fine if we compare only same-index pairs. `(partial: use /status index + a NONE read hash, retry until two nodes report the same index.)`

---

## Category B — Read correctness

### [linearizable-read-not-stale] — Linearizable/strong read never returns a stale version

| | |
|---|---|
| **Type** | Safety |
| **Property** | A `linearizable` or `strong` read never returns a per-key version older than a value previously acknowledged as committed to the client. |
| **Invariant** | `Always(read_version >= max_acked_version)` (WL, versioned register). The workload tracks, per key, the highest version it has received a committed ack for; any subsequent linearizable/strong read of that key must return `>=` that version. `Always` because this is the definition of the linearizability guarantee at `store/DESIGN.md:43`. |
| **Antithesis Angle** | Exercises `waitForLinearizableRead` (`store/store.go:2412-2460`) under leader change mid-read: the term-change branch (`2444-2445 → ErrStaleRead`) and quorum verify (`2440-2443`) must prevent a stale answer. |
| **Why It Matters** | This is the core promise clients rely on for read-after-write correctness. |

**Open Questions:**
- The read may return `ErrStaleRead`/`ErrNotLeader` legitimately; the assertion only applies to *successful* reads. Ensure the oracle ignores error responses. `(partial.)`

### [strong-read-linearized] — Strong read reflects all prior-committed writes

| | |
|---|---|
| **Type** | Safety |
| **Property** | A `strong` read (submitted through the Raft log as `COMMAND_TYPE_QUERY`) reflects every write committed before the read entry. |
| **Invariant** | `Always(strong_read reflects last_acked_write)` (WL). After the workload receives a commit ack for version V of a key, an immediately-following strong read of that key returns `>= V`. `Always` because a strong read is processed by every FSM in log order, so it is trivially linearizable (`store/DESIGN.md:44`). |
| **Antithesis Angle** | Under leader failover the strong read's `raft.Apply` (`store/store.go:1569`) may return `ErrNotLeader`/`ErrLeadershipLost` and be retried on the new leader; the check confirms the eventual successful read is not behind an earlier ack. |
| **Why It Matters** | Strong is the reference oracle for "most correct" reads; if it can be stale, nothing is trustworthy. |

**Open Questions:**
- Overlaps heavily with `linearizable-read-not-stale`; kept distinct because strong exercises a different code path (log Apply vs read-index). See relationships doc.

### [weak-read-staleness-bounded] — Weak read only from a current leader; deposed leader stops serving

| | |
|---|---|
| **Type** | Safety |
| **Property** | A `weak` read is served only by a node that currently believes it is leader; a partitioned ex-leader must stop serving weak reads once it steps down, so weak staleness stays within the documented bound. |
| **Invariant** | `AlwaysOrUnreachable(weak_read_version >= acked_version - staleness_slack)` (WL) combined with a leadership cross-check: a node returning weak data must report `is_leader`. Modeled as `AlwaysOrUnreachable` because the exact staleness slack is timing-dependent and the stale window may not be reached in every timeline. A `Sometimes` companion (see angle) records that the staleness window is actually exercised. |
| **Antithesis Angle** | Partition the leader; during the window before `raft.State()` stops returning `Leader` (`store/store.go:1585`), a weak read can be briefly stale. Antithesis controls exactly this timing. The companion `Sometimes(weak_read_observed_stale_then_recovered)` records the window is reached without ever crossing the hard bound. |
| **Why It Matters** | Weak is the default level; users must know its staleness is bounded and that a zombie leader can't serve arbitrarily old data. |

**Open Questions:**
- **The exact staleness bound is not stated in code.** CLAUDE.md says "~1s"; the real bound is a function of the Raft leader-lease / heartbeat timeout, not a literal constant in `Query`. This matters because the numeric slack in the assertion is unjustified without it — over-tight → false positives, over-loose → misses real bugs. `(needs human input: confirm the intended weak-read staleness bound / whether a leader lease is in effect.)`

### [none-read-freshness-honored] — none-level freshness bound returns ErrStaleRead

| | |
|---|---|
| **Type** | Safety |
| **Property** | A `none`-level read with a `freshness` bound returns `ErrStaleRead` rather than data staler than the bound. |
| **Invariant** | `Always(none_read_data_age <= freshness OR error == ErrStaleRead)` (WL). Drives `isStaleRead` (`store/store.go:2462-2474`). The workload issues NONE reads with a tight freshness against a partitioned follower and asserts either the data is within the bound or the call errored. `Always` because the freshness contract is a hard bound. |
| **Antithesis Angle** | Partition a follower from the leader so `raft.LastContact()` ages; the freshness computation must flip to `ErrStaleRead` once the follower's last contact exceeds the bound. |
| **Why It Matters** | `none`+`freshness` is how latency-sensitive users bound staleness; a broken bound silently serves arbitrarily old data. |

**Open Questions:**
- `FreshnessStrict` mode changes the computation; catalog the strict vs non-strict difference. `(partial: strict also considers whether a write is in flight; test both.)`

### [linearizable-upgrades-to-strong] — First linearizable read in a term upgrades to strong

| | |
|---|---|
| **Type** | Reachability (liveness of a specific internal path) |
| **Property** | The first `linearizable` read after a new leader's term begins hits the `ErrStrongReadNeeded` branch and upgrades itself to a `STRONG` read. |
| **Invariant** | `Reachable("linearizable read upgraded to strong")` **(SUT)** — a surgical `assert.Reachable`/`assert.Sometimes` at `store/store.go:2427` (the `ErrStrongReadNeeded` return) or at the upgrade site `1536-1538` where `numLRUpgraded` is incremented. This internal control-flow state is invisible to a black-box client, so it must be asserted in-process. `Reachable` (or `Sometimes(term_had_no_prior_strong_read)`) because we want to prove this important corner is exercised, not that it always happens. |
| **Antithesis Angle** | Requires frequent leader elections (crash/partition the leader repeatedly) so that new terms begin with a linearizable read arriving before any strong read — precisely the interleaving Antithesis is good at manufacturing. |
| **Why It Matters** | This upgrade is the guard (`store/DESIGN.md:131`) that stops a freshly-elected leader from returning a read based on a stale committed index. If the branch is never exercised in testing, a regression that removes it would go unnoticed. |

**Open Questions:**
- Adding the assertion is an SUT source edit (out of scope here); flagged for the workload/instrumentation phase. `(needs human input: approval to add SDK call in store/store.go.)`

### [read-index-quorum-verified] — Linearizable read performs the quorum VerifyLeader round-trip

| | |
|---|---|
| **Type** | Reachability |
| **Property** | The linearizable read path actually executes the `VerifyLeader` quorum heartbeat round-trip before serving. |
| **Invariant** | `Reachable("linearizable read verified leader via quorum")` **(SUT)** — `assert.Reachable` placed after the successful `VerifyLeader()` return in `waitForLinearizableRead` (`store/store.go:2441-2443`), gated on the read then succeeding. Not observable from the client, hence SUT-side. |
| **Antithesis Angle** | Confirms the read-index technique's quorum step runs under normal and post-partition conditions; pairs with `linearizable-read-not-stale` to show the mechanism, not just the outcome. |
| **Why It Matters** | If `VerifyLeader` were short-circuited (e.g. by a caching regression), linearizable reads would silently degrade to weak. This proves the mechanism fires. |

**Open Questions:**
- SUT source edit required. `(needs human input.)`

---

## Category C — Control plane / consensus

### [single-leader] — At most one leader per term

| | |
|---|---|
| **Type** | Safety |
| **Property** | No two nodes ever claim to be leader for the **same Raft term** (no split brain). |
| **Invariant** | `Always(max_leaders_in_any_term <= 1)` (WL). The workload reads each node's `(store.raft.state, store.raft.term)` from one `/status` call, groups the nodes reporting `Leader` by term, and asserts no term has more than one leader. `Always` because two nodes can never both win the same term — a genuine violation regardless of when each node was polled. **Corrected from the earlier `count(is_leader) <= 1` formulation**, which was term-blind: it counted raw `Leader` states across terms and produced a false positive in run `4b16...-58-3` when a deposed leader still reported `Leader` in a stale term during election churn under a network clog. See that run's triage. |
| **Antithesis Angle** | Partition-and-heal, asymmetric partitions, and clock skew probe the election/leader-lease logic for a window where two nodes both claim leadership **in the same term**; cross-term overlap during normal churn is expected and no longer flagged. |
| **Why It Matters** | Split brain → two nodes accepting divergent writes → the ledger and register invariants both break. This is the root-cause detector. |

**Open Questions:**
- Two nodes can *briefly* believe they are leader across a term boundary if `/status` is sampled at slightly different real times. Compare terms too: two leaders in the *same* term is the true violation; different terms across a sampling skew is benign. `(partial: include term in the cross-check.)`

### [leader-elected-after-crash] — A new leader emerges after leader loss

| | |
|---|---|
| **Type** | Liveness |
| **Property** | After the current leader is crashed or partitioned away, a surviving follower becomes leader. |
| **Invariant** | `Sometimes(new_leader_elected_after_prior_leader_lost)` (WL). The workload records the leader id, waits out a fault that removes it, and asserts a *different* node reports leader. `Sometimes` because it is a liveness/progress property: we require it happens in at least one timeline where quorum survives. |
| **Antithesis Angle** | Directly tests election liveness across the exact crash/partition faults Antithesis injects, over branching timelines. |
| **Why It Matters** | If elections stall, the cluster is unavailable for writes; proving re-election is the baseline liveness guarantee. |

**Open Questions:**
- Only holds when a quorum (2 of 3) survives; the workload must not assert re-election when it partitioned away the majority. `(partial: gate the Sometimes on quorum-survivable faults.)`

---

## Category D — Write path & determinism

### [queue-fifo-order] — Queued writes commit in submission order

| | |
|---|---|
| **Type** | Safety |
| **Property** | Queued writes commit in submission order: a lower queue sequence number is committed before a higher one. |
| **Invariant** | `Always(per_key_version_monotonic_via_queue)` (WL, with possible SUT help). The workload submits per-key writes with strictly increasing versions through `?queue`; a later strong read must show versions applied in submission order (no inversion). Backed by the queue's contract (`queue/queue.go:122-126`). `Always` because FIFO is a documented ordering guarantee. |
| **Antithesis Angle** | Crash/leader-change during the drain loop (`http/service.go:1740-1799`) probes whether the retry-forever path preserves order or can reorder batches on re-submission. |
| **Why It Matters** | Out-of-order application of queued writes would corrupt any order-dependent workload and violate the register's monotonicity. |

**Status:** Implemented (WL) in `test/v1/rqlite/parallel_driver_writeslog.py` (`fifo_op`) via the `writes_log` table: a run of increasing-`seq` rows is queued to one node, then read back `ORDER BY id` (commit order) and asserted non-decreasing. Assertion: `queue_preserves_fifo_order` → "queued writes from one client commit in submission order".

**Open Questions:**
- Pure workload observation proves *committed* order but not that the queue channel itself never reorders internally; a tighter check would need an SUT-side assertion on sequence monotonicity in `runQueue`. `(partial: workload-side is sufficient for the externally-visible guarantee; note the SUT option.)`

### [acked-write-survives-failover] — Acknowledged writes are durable across failover

| | |
|---|---|
| **Type** | Safety |
| **Property** | A write acknowledged as committed to the client is never lost after leader failover or crash-restart. |
| **Invariant** | `Always(acked_version_present_after_failover)` (WL). The workload records every committed ack (register version / ledger transfer); after any fault + recovery it re-reads (strong) and asserts every acked value is still present. `Always` because Raft's durability guarantee is that a committed entry survives any minority failure. |
| **Antithesis Angle** | Crash the leader immediately after ack; partition then heal; the check confirms the committed entry replicated to the quorum and survived, and that a *standard* (non-queued) ack really means committed. |
| **Why It Matters** | "I got an OK and my data vanished" is the highest-severity durability bug. |

**Status:** Implemented (WL) in `test/v1/rqlite/parallel_driver_writeslog.py` (`durability_op`): insert one row, capture its acked `last_insert_id`, then strong-read that id and assert it is present. Assertion: `acked_write_durable` → "an acknowledged write is present on a subsequent strong read".

**Open Questions:**
- Must distinguish standard-write acks (true commit) from queued `wait=false` acks (only enqueued, not durable). The oracle must only treat true-commit acks as promises. `(partial: only track standard / wait=true acks as durable.)`

### [nondeterministic-rewrite-identical] — RANDOM/time rewritten to identical literals cluster-wide

| | |
|---|---|
| **Type** | Safety |
| **Property** | Non-deterministic functions (`RANDOM()`, `datetime('now')`) are rewritten to a concrete literal before entering the Raft log, so every replica applies the identical value. |
| **Invariant** | `Always(replicas_identical_after_random_write)` (WL). A dedicated workload op inserts rows using `RANDOM()`/`datetime('now')` (rewrite on), then asserts `no-replica-divergence`-style equality across nodes for those rows. `Always` because rewriting happens once on the ingress node (`http/service.go:1305/1367/1452/1528`) and the literal is what replicates. |
| **Antithesis Angle** | Message reorder and forwarding (a write forwarded from a follower to the leader) probe whether rewriting always happens on the correct node before the Raft entry is formed. |
| **Why It Matters** | An unrewritten non-deterministic function is a silent divergence source that only manifests under specific data, making it a classic latent bug. |

**Open Questions:**
- Confirm forwarded writes (received by a follower, proxied to leader) are rewritten before or after forwarding — the call sites are on the HTTP ingress node, so a forwarded write should already carry the literal. `(partial: verify the cluster-forward path preserves the rewritten command rather than re-parsing.)`

---

## Category E — Snapshot & recovery

### [snapshot-restore-consistent] — Restore reproduces leader state at the snapshot index

| | |
|---|---|
| **Type** | Safety |
| **Property** | After the Raft log is truncated to index N and a node restores from snapshot, its DB state equals the leader's state at N; CRC catches any corruption. |
| **Invariant** | `Always(restored_node_matches_leader_at_index)` (WL safety net) + `Reachable("node restored from snapshot")` **(SUT)** for the path itself. After a node that restored (`fsmRestore`, `store/store.go:2760-2820`) rejoins, `no-replica-divergence` and `acked-write-survives-failover` must still hold for it. `Always` for the content-equality safety net; a `Reachable` at the restore path proves it was actually exercised. |
| **Antithesis Angle** | Force snapshots (small `-raft-snap`), then crash/rejoin a node so it must catch up via snapshot install rather than log replay; verify no divergence and no lost acked writes. |
| **Why It Matters** | Snapshot install is how lagging/new nodes catch up; a bug here corrupts a node's state without any write ever being wrong. |

**Open Questions:**
- Proving the node truly went through *snapshot install* (not log replay) needs an SUT-side `Reachable` in `fsmRestore`; workload can only confirm the end-state matches. `(partial: workload safety net + optional SUT reachability.)`

### [reap-crash-idempotent] — Crash mid-reap recovers with no data loss

| | |
|---|---|
| **Type** | Safety |
| **Property** | A crash during snapshot reaping / log truncation recovers via idempotent plan replay with no data loss. |
| **Invariant** | `Always(no_data_loss_after_reap_crash)` (WL safety net via `ledger-conservation` + `acked-write-survives-failover`) + `Reachable("reap resumed after crash")` **(SUT)** in the reap plan-replay path (`snapshot/DESIGN.md:100,164`). `Always` for the conservation/durability safety net; `Reachable` to confirm the crash-mid-reap interleaving is actually hit. |
| **Antithesis Angle** | Crash a node precisely during the reap window (Antithesis can hit narrow timing windows across branches); recovery must replay the idempotent plan and lose nothing. |
| **Why It Matters** | Reaping mutates on-disk snapshot structure; a non-idempotent crash-recovery could truncate a log entry the DB state doesn't yet reflect, losing committed writes. |

**Open Questions:**
- The exact reap window is short and internal; without an SUT-side reachability marker we can't confirm we hit it, only that conservation held. `(needs human input: SUT reachability marker in the reap path for meaningful coverage.)`

---

## Category F — Fault-tolerance liveness

### [progress-under-fault] — Writes get acknowledged despite active faults

| | |
|---|---|
| **Type** | Liveness |
| **Property** | A write is eventually acknowledged even while fault injection (partition/crash of a minority) is active or recently active. |
| **Invariant** | `Sometimes(write_acked_during_or_after_fault)` (WL). The workload asserts `Sometimes` that a write submitted while a minority-fault is active later returns success. `Sometimes` because it is progress under adversity — required in at least one timeline where a quorum survives. |
| **Antithesis Angle** | Keeps a minority node down/partitioned while driving writes; the queued retry-forever drain (`http/service.go:1740-1799`) and leader stability under minority fault must still commit. |
| **Why It Matters** | A cluster that only makes progress in perfectly healthy conditions is useless; this proves fault-tolerant availability. |

**Open Questions:**
- Distinguish "acked during fault" from "acked after heal"; both prove liveness but the former is stronger. `(partial: record fault-active timestamp vs ack time.)`

### [write-eventually-commits] — Queued write with wait=true eventually succeeds

| | |
|---|---|
| **Type** | Liveness |
| **Property** | A queued write submitted with `wait=true` eventually returns success (its flush channel closes), demonstrating the retry-forever drain path commits. |
| **Invariant** | `Sometimes(queued_wait_true_returned_success)` (WL). The workload submits `?queue&wait=true` writes under churn and asserts `Sometimes` one returns success. `Sometimes` because it is a liveness guarantee about the drain loop draining (`http/service.go:1761-1792`). |
| **Antithesis Angle** | Leader changes during the drain force `proxy.Execute` to retry against the new leader until commit; the flush channel closing proves the drain eventually made progress. |
| **Why It Matters** | Queued writes are the recommended high-throughput path; proving the drain always eventually commits validates their durability story under churn. |

**Open Questions:**
- If a leader never re-forms (majority lost), `wait=true` blocks forever by design; the `Sometimes` must be scoped to quorum-survivable timelines. `(partial.)`
