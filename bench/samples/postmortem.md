# Postmortem: duplicate billing events on the checkout queue

## Summary

Between 14:02 and 14:19 UTC on 2026-07-18, the checkout queue delivered 1,842 duplicate billing
events. Roughly 300 customers were charged twice. The root cause was a consumer restart during a
rebalance: the service committed offsets before the downstream billing call completed, so a
restart replayed events whose side effects had already happened.

## Timeline

- 14:02 — a node running the queue consumer was evicted by the cluster autoscaler.
- 14:03 — the consumer group rebalanced and the partition moved to another node.
- 14:04 — the new consumer replayed the last 40 seconds of events because the offset commit was
  ahead of the billing write.
- 14:05 — the first duplicate charge alert fired; it was routed to a low-priority channel.
- 14:11 — support reported duplicate receipts from three customers.
- 14:14 — the on-call engineer paused the consumer.
- 14:19 — the consumer was resumed with idempotency keys enabled.

## Root cause

The consumer did the billing request and the offset commit in parallel and did not wait for the
billing response. This is safe only if the downstream operation is idempotent, and it was not.
The original design assumed at-least-once delivery was acceptable because the billing provider
deduplicated by request id, but the service was not sending a stable request id: it generated a
new uuid per attempt.

## What went well

- The alert fired within three minutes.
- Pausing the consumer stopped the bleeding with no data loss.
- The fix was a configuration change plus a one-line idempotency key, not a schema migration.

## What went badly

- The duplicate-charge alert was classified as low priority.
- We had no runbook for pausing a consumer; the on-call engineer worked it out live.
- The provider's deduplication behaviour was documented but not tested.

## Action items

1. Send `Idempotency-Key` derived from the event id, not a fresh uuid. Owner: payments. Due: done.
2. Commit offsets only after the billing call succeeds, and add a retry budget. Owner: payments.
3. Add a runbook for pausing and resuming the checkout consumer. Owner: on-call. Due: 2026-07-25.
4. Raise the duplicate-charge alert to page severity. Owner: observability. Due: 2026-07-22.
5. Add an integration test that kills the consumer mid-batch and asserts exactly one charge per
   event. Owner: payments. Due: 2026-08-01.

## Lessons

At-least-once delivery is only safe when every side effect is idempotent. "The provider
deduplicates" is not a guarantee unless we send a stable key. The 17-minute detection delay was
mostly alert routing, not detection.
