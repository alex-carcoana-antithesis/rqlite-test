# linearizable-upgrades-to-strong

**Side:** SUT-side (surgical SDK assertion in `store/store.go`). REQUIRES SUT SOURCE EDIT.

## Guarantee
The first `linearizable` read after a new leader's term begins hits the
`ErrStrongReadNeeded` branch and upgrades itself to a `STRONG` read.

## Why it must be SUT-side
The upgrade is pure internal control flow. A black-box client sees a normal
linearizable read succeed; it cannot tell whether the read went through the read-index
fast path or was upgraded to a strong (log Apply) read. The only faithful check is an
in-process `assert.Reachable` (or `assert.Sometimes(term_had_no_prior_strong_read)`).

## Where the assertion goes
- At `store/store.go:2427` — the `return ErrStrongReadNeeded` branch inside
  `waitForLinearizableRead`, OR
- At `store/store.go:1536-1538` — the caller's upgrade site where `level` is set to
  `STRONG` and `numLRUpgraded.Add(1)` runs.

The `numLRUpgraded` counter already exists; an alternative low-touch approach is to
export/observe that counter, but a direct `assert.Reachable` at the branch is clearest.

## Code paths
- Term-establishment check: `currReadTerm != s.strongReadTerm.Load()`
  (`store/store.go:2427`).
- `strongReadTerm` is set only by a successful strong read (`1580`).
- Rationale: `store/DESIGN.md:43,131` — a freshly elected leader has not proven it
  committed anything in its term, so the first linearizable read must upgrade.

## What breaks if violated / if branch never exercised
If this upgrade is removed or regressed, a freshly-elected leader could serve a
linearizable read based on a stale committed index. If tests never exercise the
branch, such a regression ships silently.

## Antithesis angle / timing
Requires frequent elections: repeatedly crash/partition the leader so new terms begin,
and ensure a linearizable read arrives in the new term *before* any strong read has
run. This precise ordering is what Antithesis branch exploration manufactures.

## Open questions
- **(needs human input)** Adding the `assert.Reachable` is an SUT source change, out
  of scope for this read-only scratchbook. Needs approval + the SDK dependency added
  to the SUT build.
