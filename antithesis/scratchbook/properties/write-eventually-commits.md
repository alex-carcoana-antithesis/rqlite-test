# write-eventually-commits

**Side:** Workload-side (WL).

## Guarantee
A queued write submitted with `wait=true` eventually returns success (its flush
channel closes), demonstrating the retry-forever drain path commits.

## Workload model
Submit `?queue&wait=true` writes under leader churn and assert `Sometimes` one returns
success. Success == the flush channel closed == the batch was applied.
`Sometimes(queued_wait_true_returned_success)`.

## Code paths
- Queued submit: `http/service.go:1279-1337`.
- Drain / flush-channel close on apply: `http/service.go:1761-1792`.
- `Queue.Write` flush channel semantics: `queue/queue.go:122-132`.

## What breaks if violated
Queued writes are the recommended high-throughput path. Proving the drain always
eventually commits under churn validates their durability story — otherwise a
`wait=true` caller could block forever even though a leader exists.

## Antithesis angle / timing
Leader changes during the drain force `proxy.Execute` to retry against the new leader
until commit; the flush channel closing proves the drain eventually made progress
despite churn.

## Open questions
- If a majority is permanently lost, `wait=true` blocks forever by design; scope the
  `Sometimes` to quorum-survivable timelines. (partial)
