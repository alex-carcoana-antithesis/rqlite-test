---
sut_path: /Users/alexcarcoana/Desktop/rqlite
commit: 28a7a521174dc4c2e4334b6ee552809c9567f030
updated: 2026-07-06
external_references: []
---

# Existing Antithesis Assertions — Scan Result

**Result: NO Antithesis SDK assertions exist in this codebase.**

Evidence:

- The module `github.com/antithesishq/antithesis-sdk-go` is **not** present in
  `go.mod` (module `github.com/rqlite/rqlite/v10`, go 1.26). No require entry, no
  indirect dependency.
- A case-insensitive search for the string `antithesis` across all Go sources,
  `go.mod`, and `go.sum` returns **zero** occurrences:

  ```
  grep -ri "antithesis" . --include="*.go" --include="go.mod" --include="go.sum"
  # (no output, exit 1)
  ```

- Consequently there are no calls to `assert.Always`, `assert.AlwaysOrUnreachable`,
  `assert.Sometimes`, `assert.Reachable`, `assert.Unreachable`, no
  `lifecycle.SetupComplete`, and no `random.GetRandom` anywhere in the tree.

Existing testing infrastructure that we can *reuse* (but which contains no
Antithesis instrumentation):

- Go unit/integration tests throughout (`store/*_test.go`, `db/*_test.go`, etc.).
- Python E2E harness under `system_test/e2e/` — notably `helpers.py` with the `Node`
  and `Cluster` classes and leadership/readiness probes. These are ordinary
  assertions in a pytest-style driver, not Antithesis SDK assertions, but the client
  helpers are directly reusable in an Antithesis workload container.

**Implication:** every property in `property-catalog.md` is greenfield. Workload-side
properties will be asserted from the driver container using the Antithesis SDK (Go or
Python bindings, once the SDK dependency is added to the workload — not the SUT).
The handful of properties that inspect internal store state
(`linearizable-upgrades-to-strong`, `read-index-quorum-verified`, and the
snapshot/reap reachability probes) require adding surgical `assert.*` /
`assert.Reachable` calls inside `store/store.go` — which is an SUT source change and
therefore out of scope for this read-only scratchbook, but flagged here and in each
evidence file so an implementer knows exactly where they must land.
