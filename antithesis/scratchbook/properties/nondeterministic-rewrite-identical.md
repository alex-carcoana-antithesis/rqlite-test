# nondeterministic-rewrite-identical

**Side:** Workload-side (WL).

## Guarantee
Non-deterministic functions (`RANDOM()`, `datetime('now')`) are rewritten to a
concrete literal before entering the Raft log, so every replica applies the identical
value.

## Workload model
A dedicated op inserts rows using `RANDOM()` / `datetime('now')` with rewriting on
(default). Then, at quiescence, assert the inserted rows are identical across all
nodes (same technique as no-replica-divergence, scoped to these rows). Optionally also
run with `?norwrandom` / `?norwtime` as a negative control (expect divergence
possible — do NOT assert equality there). `Always` for the rewrite-on case.

## Code paths
- Rewriter: `command/sql/processor.go:43-78` (`Process`), visitor `171-199`
  (datetime/random), defaults true `138-140`, skips `ORDER BY RANDOM()`.
- Ingress rewrite call sites (pre-Raft, on the receiving HTTP node):
  `http/service.go:1305` (queued), `1367` (execute), `1452` (query), `1528`
  (request). The concrete literal is what enters the Raft command.
- Opt-outs parsed: `http/query_params.go:112-119`.

## What breaks if violated
An unrewritten non-deterministic function evaluates differently per node → silent
replica divergence that only manifests for specific data. Classic latent
distributed-DB bug.

## Antithesis angle / timing
Message reorder + write forwarding (a write received by a follower and proxied to the
leader): rewriting must happen on the ingress node before the Raft entry is formed, so
a forwarded write should already carry the literal.

## Open questions
- Verify the cluster-forward path (follower → leader via `cluster/`) transmits the
  already-rewritten command rather than re-parsing raw SQL on the leader. If it
  re-parses, the rewrite must still be deterministic. (partial)
- New/other non-deterministic functions beyond random/datetime are not rewritten; out
  of the workload's scope but worth noting. (partial)
