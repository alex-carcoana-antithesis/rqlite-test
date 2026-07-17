# no-negative-balance

**Side:** Workload-side (WL).

## Guarantee
No account balance is ever observed below zero.

## Workload model
The debit leg of every transfer is guarded: `UPDATE accounts SET balance = balance -
amt WHERE id=A AND balance >= amt`. If the guard fails the debit is a no-op and the
paired credit must also not apply (same bulk entry, evaluate credit conditionally on
rows-affected, or model the transfer as a single conditional statement). Every balance
read asserts `balance >= 0`.

Assertion type: `AlwaysOrUnreachable(balance >= 0)` — some timelines may never drive a
debit large enough to test the guard, so we don't demand the state be reached.

## Code paths
- Same write/apply path as ledger-conservation
  (`store/store.go:1706`, `command_processor.go:45-146`).
- Reads: NONE/weak/linearizable all acceptable for the check since it's a `>= 0`
  bound, not a freshness bound.

## What breaks if violated
A negative balance means the conditional debit was evaluated against a stale or
uncommitted balance — a lost-isolation / stale-read-feeding-a-write bug.

## Antithesis angle / timing
Concurrent transfers hammering the same hot account under leader churn: does the
`WHERE balance >= amt` guard see a committed balance, or can two debits both pass the
guard against the same pre-image and drive the account negative?

## Open questions
- None.
