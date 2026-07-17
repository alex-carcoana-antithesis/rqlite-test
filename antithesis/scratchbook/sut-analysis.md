---
sut_path: /Users/alexcarcoana/Desktop/rqlite
commit: 28a7a521174dc4c2e4334b6ee552809c9567f030
updated: 2026-07-06
external_references: []
---

# rqlite SUT Analysis — Consensus & Read Consistency

Scope of this scratchbook is **core consensus + read-consistency correctness**: the
Raft/store FSM, the four read levels (`none`/`weak`/`linearizable`/`strong`), the
write paths (standard/queued/bulk), non-deterministic function rewriting, and
snapshot/restore as it affects consensus correctness. CDC, cloud backup/restore,
and extensions are explicitly out of scope.

## 1. High-level architecture

rqlite is a single Go binary (`cmd/rqlited`) that wraps SQLite behind a Raft
consensus layer. A client talks HTTP to any node; writes are funneled through Raft
so every node applies the identical sequence of commands to its own local SQLite
database. The design principle is "single binary, no external dependencies" — Raft
log storage is BoltDB (`go.etcd.io/bbolt`), consensus is `hashicorp/raft`, and the
SQLite driver is a fork (`github.com/rqlite/go-sqlite3`) with extra hooks.

Key packages for this scope:

- **`store/`** — the heart. Wraps `hashicorp/raft`, implements the Raft FSM
  (`fsmApply`, `fsmSnapshot`, `fsmRestore`), and exposes `Execute`, `Query`,
  `Request` entry points. This is where consistency levels are enforced and where
  the single serialized mutation point lives.
- **`store/command_processor.go`** — `CommandProcessor.Process`: the one place any
  Raft-log command is translated into a SQLite mutation. Every replica runs this in
  log order.
- **`command/`** — protobuf command definitions (`command/proto/`) and the
  non-deterministic SQL rewriter (`command/sql/processor.go`).
- **`http/`** — REST API. Parses consistency levels and rewrite opt-outs
  (`query_params.go`), rewrites non-deterministic SQL, dispatches to the store, and
  hosts the write queue drain loop (`service.go`).
- **`queue/`** — the batching queue backing `?queue` writes; guarantees FIFO
  ordering and hands back monotonically increasing sequence numbers.
- **`snapshot/`** — the custom Raft snapshot store (incremental WAL-based snapshots,
  CRC integrity, crash-safe reaping).
- **`cluster/`** — inter-node protobuf-over-TCP: request forwarding to the leader,
  joins/removes.

## 2. Store / FSM: the serialization core

### 2.1 The single mutation point

Every state change on every node passes through `CommandProcessor.Process`
(`store/command_processor.go:45-146`). It unmarshals a `proto.Command`, switches on
`Command_Type`, and applies exactly one of:

- `COMMAND_TYPE_QUERY` (52-58) — a strong read run through the log; **not** a
  mutation (returns `false` for the mutated flag).
- `COMMAND_TYPE_EXECUTE` (59-65) — a write; returns `true` (mutated).
- `COMMAND_TYPE_EXECUTE_QUERY` (66-72) — unified request; mutated flag is
  `ExecuteQueryResponses(r).Mutation()`, i.e. it depends on whether any statement
  actually mutated.
- `COMMAND_TYPE_LOAD` (73-96) — swaps the entire underlying SQLite DB to a
  restored file; mutated `true`.
- `COMMAND_TYPE_LOAD_CHUNK` (97-140) — chunked load, streaming a DB in pieces.

Because this dispatch runs inside the Raft FSM apply, and Raft delivers the same log
to every node in the same order, all replicas that reach applied index N have
executed the identical command sequence. This is the backbone of replica
determinism.

### 2.2 fsmApply and index invariants

`fsmApply` (`store/store.go:2491-2553`) is the FSM `Apply` callback. It:

- Advances `fsmIdx`/`fsmTerm` to the log entry being applied (monotonic ordering).
- Calls `CommandProcessor.Process` for the mutation.
- Advances `dbAppliedIdx` **only when the command actually mutated** the DB. So a
  strong-read `COMMAND_TYPE_QUERY` moves `fsmIdx` but not `dbAppliedIdx`.
- On `LOAD`/`LOAD_CHUNK`, invalidates any in-flight snapshot state and CDC watermark
  (2543-2551), because the DB was wholesale replaced.
- Records `fsmUpdateTime`/`appendedAtTime` used later by the staleness computation.

The distinction between `fsmIdx` (log position) and `dbAppliedIdx` (last mutation
position) matters for the linearizable read wait: the read waits for the FSM to
reach a *commit index*, and the "did the DB content actually change" question is
separate.

### 2.3 Write path

Writes enter via `Execute` (`store/store.go:1447-1499`) or the unified `Request`
(`1620-1710`). Both check leadership and readiness (`1464-1469`) before doing
anything, then marshal a `proto.Command` and call `raft.Apply` (the `Request` write
Apply is at `1706`). If the node is not the leader they return `ErrNotLeader`; the
HTTP layer / cluster layer forwards to the leader. `raft.Apply` blocks until the
entry is committed (replicated to a quorum and applied locally) for standard writes.

### 2.4 Query path and the four consistency levels

`Query` (`store/store.go:1505-1594`) and the read side of `Request`
(`1620-1710`) enforce consistency:

- **AUTO** (`~1521`) resolves to `WEAK` on a voter, `NONE` on a non-voter. Our
  topology is all voters, so AUTO == WEAK.
- **NONE** (`1588`, `1666`) — read straight from local SQLite with no leadership
  check. If a `freshness` bound is supplied, `isStaleRead` (`2462-2474`) can reject
  the read with `ErrStaleRead` when local data is older than the bound. Fastest,
  can be stale.
- **WEAK** (`1585`, `1668`) — the node must currently believe it is the Raft leader
  (`s.raft.State() != raft.Leader` → `ErrNotLeader`). No quorum round-trip, so a
  just-partitioned ex-leader can serve a weak read during the brief window before it
  learns it lost leadership. This is the documented ~staleness window.
- **LINEARIZABLE** (`1533`, `1641`) — calls `waitForLinearizableRead`
  (`2412-2460`). See §2.5.
- **STRONG** (`1545-1583`) — the read is itself submitted to the Raft log as a
  `COMMAND_TYPE_QUERY` entry via `raft.Apply` (`1569`). Because every FSM processes
  it in log order, it trivially reflects all writes committed before it — it is
  "trivially linearizable" (`store/DESIGN.md:44`). Slowest; mainly for testing and
  as the linearizable upgrade target.

### 2.5 The linearizable read protocol (subtle, high-value target)

`waitForLinearizableRead` (`store/store.go:2412-2460`) implements the Raft
dissertation §6.4 read-index technique, plus a correctness wrinkle:

1. **Term-establishment check (2427):** if `currReadTerm != s.strongReadTerm.Load()`
   — i.e. no strong read has yet gone through the log in *this* term — it returns
   `ErrStrongReadNeeded`. The caller (`Query`, 1536-1538) then **upgrades the read
   to STRONG** and increments `numLRUpgraded`. Rationale (`store/DESIGN.md:43,131`):
   a freshly elected leader has not proven it committed anything in the new term, so
   a naive read-index could reflect a stale committed index. Forcing one strong read
   per term establishes the commit point. **This upgrade is an internal state that a
   black-box workload cannot observe** — it requires SUT-side instrumentation.
2. **Leader/ready re-check (2431-2436).**
3. **Read index capture + quorum verify (2440-2443):** `readIndex :=
   raft.CommitIndex()`, then `VerifyLeader()` (`1596-1618`) does a heartbeat
   round-trip to confirm a quorum still regards this node as leader.
4. **Term-stability check (2444-2445):** if the term changed during verification,
   return `ErrStaleRead`.
5. **Wait for local FSM to reach `readIndex` (2453-2458):** subscribe to the FSM
   target; on reach, the read proceeds; on timeout, `ErrWaitForFSMTimeout`.

The guarantee (`store/DESIGN.md:43`): a linearizable read reflects everything
committed before the request started.

## 3. Non-deterministic function rewriting

SQLite functions like `RANDOM()` and `datetime('now')` would evaluate differently on
each replica, breaking determinism. rqlite rewrites them to concrete literals on the
**receiving HTTP node, before the command enters the Raft log**, so all replicas
apply the identical literal.

- Rewriter: `command/sql/processor.go:43-78` (`Process`), with the AST visitor at
  `171-199` handling `datetime`/`random`. Rewriting defaults on (`138-140`);
  `ORDER BY RANDOM()` is deliberately skipped (rewriting it would be meaningless /
  harmful).
- Call sites (all pre-Raft, on the ingress node): `http/service.go:1305` (queued),
  `1367` (execute), `1452` (query), `1528` (request).
- Opt-outs: `?norwrandom` / `?norwtime` parsed at `http/query_params.go:112-119`.

Because the concrete literal is what is serialized into the Raft command, every
node's FSM sees the same value → identical DB content. `no-replica-divergence`
validates this end-to-end.

## 4. Write modes

- **Standard** — single `raft.Apply`, blocks until committed.
- **Bulk** — multiple statements in one request → one Raft entry, better throughput,
  atomic as one FSM apply.
- **Queued** (`?queue`) — HTTP `queuedExecute` (`http/service.go:1279-1337`) pushes
  statements into `queue/queue.go`. `Queue.Write` (`122-132`) returns a
  monotonically increasing sequence number and guarantees a lower-seq batch is
  transmitted on the queue's output channel before a higher-seq batch (FIFO). The
  drain loop `runQueue` (`http/service.go:1740-1799`) reads batches and calls
  `proxy.Execute`, **retrying forever** through leader changes until the batch
  commits; a `wait=true` caller blocks on the flush channel that closes when the
  batch is applied. Queued writes trade a small durability window (unflushed
  in-memory batch can be lost on crash) for large throughput gains.

## 5. Snapshot & restore

- **Snapshot:** `fsmSnapshot` (`store/store.go:2560+`) checkpoints the WAL with
  `synchronous=FULL` (~2581) and hands a snapshot to the custom store. The snapshot
  package (`snapshot/DESIGN.md`) does incremental WAL-based snapshots: the snapshot
  store is ground truth for the DB state at the truncation index N
  (`snapshot/DESIGN.md:7`). CRC integrity via `snapshot/crc_checker.go`
  (`snapshot/DESIGN.md:52`).
- **Reaping / log truncation:** old snapshots are reaped through an idempotent plan
  that is crash-safe — a crash mid-reap is recovered by replaying the plan, with no
  data loss (`snapshot/DESIGN.md:100,164`).
- **Restore:** `fsmRestore` (`store/store.go:2760-2820`) installs a snapshot and
  resets `fsmIdx`/`dbAppliedIdx`/terms (2810-2818) so the node's applied position
  matches the snapshot's index. After restore the node's DB must equal the leader's
  state at N.

These paths are in-scope only insofar as they affect consensus correctness (a
restored/snapshotted node must not diverge and must not lose acknowledged writes).

## 6. Leader election & membership

- `hashicorp/raft` runs elections; `VerifyLeader` (`store/store.go:1596-1618`) is
  the quorum leadership probe used by linearizable reads.
- Bootstrap: `-bootstrap-expect N` (`cmd/rqlited/config_flags.go:178`,
  boot logic `cmd/rqlited/main.go:583-653`) waits for N nodes then forms the
  cluster atomically; `-join`/`-join-attempts` and DNS/Consul/etcd discovery
  (`main.go:612-700`) are alternatives.
- Read-only nodes (`-raft-non-voter`) replicate but don't vote (out of our topology,
  but relevant to AUTO→NONE resolution).

## 7. Concurrency model

- The Raft FSM apply is single-threaded per node — commands apply one at a time in
  log order. This is what makes replica content a deterministic function of the log.
- The write queue has its own goroutine (`queue.run`) and a lock held across
  `Write`. The HTTP drain loop is a separate goroutine.
- Reads (`none`/`weak`) run concurrently against SQLite (WAL mode allows concurrent
  readers); `strong` reads serialize through the log.
- Atomics (`fsmIdx`, `dbAppliedIdx`, `strongReadTerm`, `fsmUpdateTime`,
  `appendedAtTime`) carry cross-goroutine state; these are exactly the fields the
  linearizable and staleness logic reads.

## 8. Failure-prone areas (where Antithesis should push)

1. **Linearizable read term-establishment (`store/store.go:2427`)** — the
   first-read-per-term upgrade. If broken, a new leader can serve a stale read. Hard
   to hit without leader churn; needs SUT-side instrumentation to confirm the branch
   is exercised.
2. **Weak read on a deposed leader** — the window between losing quorum contact and
   `raft.State()` no longer returning `Leader`. Exact staleness bound is
   undocumented in code (see open questions).
3. **Non-deterministic rewriting** — if any RANDOM/time path escapes rewriting (e.g.
   a new function, or the ingress-node-only rewrite missing a forwarded path),
   replicas diverge silently.
4. **Queued write durability window** — in-memory batch lost on crash; `wait=true`
   semantics must still hold (no ack unless committed).
5. **Snapshot/restore correctness** — a restored node must match leader state at N;
   CRC must catch corruption; crash mid-reap must not lose data.
6. **Split brain** — two nodes both reporting leader under partition/heal timing.

## 9. Deployment assumption for the Antithesis harness

Topology: **3 rqlited voter nodes** (minimum quorum, tolerates 1 failure), forming
via `-bootstrap-expect 3 -join node1:4002,node2:4002,node3:4002`, plus **one
workload/driver container**. The existing `Dockerfile` and env-var-driven
`docker-entrypoint.sh` are reusable for per-node config. The workload maintains two
oracle-checkable data models:

- a **conserved-sum ledger** (accounts with random transfers; `SUM(balance)` is
  invariant), and
- a **per-key versioned register** (monotonically increasing version per key),

which between them make most safety properties checkable purely from the workload
side, with a handful of internal-state properties requiring surgical SUT-side SDK
assertions in `store/store.go`.

The client library `system_test/e2e/helpers.py` is reusable: `Node`
(`helpers.py:93`) exposes `is_leader`/`is_follower`/`is_voter`/`wait_for_leader`/
`ready` probes and `Cluster` (`helpers.py:713`) offers `cross_check_leader` for the
single-leader assertion.
