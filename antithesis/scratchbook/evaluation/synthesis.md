---
sut_path: /Users/alexcarcoana/Desktop/rqlite
commit: 28a7a521174dc4c2e4334b6ee552809c9567f030
updated: 2026-07-06
external_references: []
---

# Evaluation Synthesis

An evaluation pass over the 18-property catalog for the rqlite consensus /
read-consistency scope. Findings are grouped; actions taken during cataloging are
noted inline.

## 1. Antithesis-fit

**Strong fit.** rqlite is a deterministic replicated state machine whose entire
correctness story is about surviving partitions, crashes, reorder, and clock skew —
exactly Antithesis's fault vocabulary. The catalog leans on two properties that make
this a near-ideal target:

- The **single serialized mutation point** (`store/command_processor.go:45-146`)
  means replica content is a pure function of the Raft log. `no-replica-divergence`
  turns any non-determinism into a loud, catchable failure.
- The **read-consistency ladder** gives graded oracles: `strong` reads are a trusted
  reference the workload can compare weaker reads against.

The conserved-sum ledger + versioned register workload model makes 14 of 18
properties checkable purely from the driver container with no SUT changes — high
leverage.

## 2. Coverage balance

Categorized coverage (catalog categories A–F):

| Area | Properties | Balance note |
|---|---|---|
| Data integrity | ledger-conservation, no-negative-balance, no-replica-divergence | Strong — 3 broad alarms. |
| Read correctness | linearizable-read-not-stale, strong-read-linearized, weak-read-staleness-bounded, none-read-freshness-honored, linearizable-upgrades-to-strong, read-index-quorum-verified | Deepest cluster (6); covers all four levels + 2 mechanism markers. |
| Control plane | single-leader, leader-elected-after-crash | Both halves (safety + liveness) of the leader guarantee. |
| Write path | queue-fifo-order, acked-write-survives-failover, nondeterministic-rewrite-identical | Ordering, durability, determinism — well covered. |
| Snapshot/recovery | snapshot-restore-consistent, reap-crash-idempotent | Deliberately shallow (2), per scope: cataloged for consensus-safety impact only. |
| Fault liveness | progress-under-fault, write-eventually-commits | Adequate liveness floor. |

Safety/liveness split: 12 safety (Always/AlwaysOrUnreachable), 6 liveness/reachability
(Sometimes/Reachable). Healthy — safety-dominant, which suits a database, with enough
liveness/reachability to prove the interesting states are actually reached and avoid a
"green because nothing happened" run.

**Gaps noted (intentionally out of scope or deferred):**
- Membership *changes* (add/remove voter at runtime) are only lightly touched via
  bootstrap; joint-consensus correctness is not a dedicated property. Candidate future
  addition if scope widens.
- Read-only (non-voter) node behavior and AUTO→NONE resolution are not a dedicated
  property (topology is all voters). Noted, not cataloged.
- Cluster-forward (follower→leader proxy) determinism is folded into
  `nondeterministic-rewrite-identical`'s open questions rather than being its own
  property.

## 3. Implementability

**Workload-side (14) — implementable today, no SUT edits:**
ledger-conservation, no-negative-balance, no-replica-divergence,
linearizable-read-not-stale, strong-read-linearized, weak-read-staleness-bounded,
none-read-freshness-honored, single-leader, leader-elected-after-crash,
queue-fifo-order, acked-write-survives-failover, nondeterministic-rewrite-identical,
progress-under-fault, write-eventually-commits.
These need only the driver container (ledger + versioned register oracle) and the
reusable `system_test/e2e/helpers.py` client. The Antithesis SDK is added to the
*workload*, not the SUT.

**Need surgical SUT-side instrumentation (`store/store.go` / snapshot path):**
- `linearizable-upgrades-to-strong` — `assert.Reachable` at `store/store.go:2427` or
  the upgrade site `1536-1538`. Internal control flow, invisible to a client.
- `read-index-quorum-verified` — `assert.Reachable` after `VerifyLeader()` at
  `store/store.go:2441-2443`.
- `snapshot-restore-consistent` — workload safety net is enough for the *outcome*, but
  a `Reachable` in `fsmRestore` (`store/store.go:2760`) is needed to prove the restore
  path was actually exercised.
- `reap-crash-idempotent` — workload conservation is the safety net, but a `Reachable`
  in the reap plan-replay path (`snapshot/DESIGN.md:100,164`) is needed for meaningful
  coverage of the crash-mid-reap window.

All four SUT-side additions are single-line `assert.Reachable`/`assert.Sometimes`
calls; they require adding `github.com/antithesishq/antithesis-sdk-go` to the SUT
build and are **out of scope for this read-only scratchbook** (flagged in each
evidence file as `needs human input` / SUT source edit).

## 4. Wildcard / open risks

- **Weak-read staleness bound is unquantified** (`weak-read-staleness-bounded`). The
  bound is governed by the Raft leader-lease/heartbeat timeout, not a code literal.
  The assertion's `slack` constant is unjustified until confirmed — the single most
  important `needs human input` item because a wrong constant either false-positives
  or misses zombie-leader bugs.
- **Sampling non-atomicity** for cross-node checks (`single-leader`,
  `no-replica-divergence`): mitigated by comparing term/applied-index, but worth
  validating the probes don't produce false alarms under real-time skew.
- **Ack-type discipline** (`acked-write-survives-failover`): the oracle must treat only
  true-commit acks as durability promises; a bug in the workload's ack bookkeeping
  would mask or fabricate failures. Called out in the evidence file.

## 5. Actions taken during cataloging

- Split the original single "no-replica-divergence covers rewriting" idea into
  `no-replica-divergence` (broad) + `nondeterministic-rewrite-identical` (targeted),
  so a rewrite regression is localizable rather than just showing up as generic
  divergence.
- Chose `AlwaysOrUnreachable` (not `Always`) for `no-negative-balance` and the weak-
  read bound, because those states may not be driven in every timeline.
- Modeled the two internal read-mechanism properties as `Reachable`/`Sometimes` and
  explicitly tagged them SUT-side, avoiding the trap of asserting an unobservable
  internal state from the workload.
- Kept every uncertain quantity (weak-read bound, freshness units/strict mode,
  forward-path rewriting) in Open Questions with a stated why-it-matters rather than
  hiding it.

## Conclusion

The catalog is **implementable**: 14 properties ship with the workload alone; 4 need
single-line SUT-side reachability/assert markers that are cleanly identified by
file:line. Coverage is safety-dominant with a sufficient liveness/reachability floor,
balanced across data integrity, all four read levels, control plane, write path, and
(deliberately shallow) snapshot recovery. The main outstanding real-world unknown is
the weak-read staleness bound, which is escalated as `needs human input`.
