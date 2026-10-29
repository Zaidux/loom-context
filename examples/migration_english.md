# Objective

Migrate the billing service from the legacy Stripe SDK to the new payments
client, and make sure that the migration is fully backwards compatible for all
existing webhook consumers, without any downtime for the checkout flow, and
without changing the shape of the events that we publish to the internal bus.

# Definition of done

All existing webhook consumers continue to receive events with the same shape,
the checkout flow handles at least 200 requests per second in the load test,
and the staging environment has been running on the new client for 48 hours
without a single error in the payments dashboard.

# Constraints

- You must keep the legacy event schema for at least two release cycles.
- You must never change the public webhook signature verification path.
- Do not rotate the Stripe API keys during the migration window.
- Avoid any downtime for the checkout flow, including during the cutover.
- You must keep the feature flag `billing.new_client` defaulting to off.
- Do not delete the legacy adapter until the two release cycles have passed.

# Current state

- repo: acme/billing at branch release/2026.10
- migration stage: shadow traffic at 10 percent
- legacy adapter: still the source of truth for webhooks
- new client version: 4.2.1
- feature flag default: off

# Evidence

- The staging load test reached 180 requests per second before the p99 latency
  crossed 400 milliseconds (confidence 0.90)
- The legacy adapter adds roughly 12 milliseconds of overhead per webhook
  (confidence 0.85)
- The new client emits `payment_intent.succeeded` with a slightly different
  field ordering but the same fields (confidence 0.95)
- The shadow traffic run produced 3 mismatches out of 10,000 events
  (confidence 0.80)
- The staging load test reached 180 requests per second before the p99 latency
  crossed 400 milliseconds (confidence 0.90)

# Open questions

- Do any webhook consumers depend on field ordering rather than field names?
- Is the 200 requests per second target measured at the edge or at the service?
- Does the new client retry idempotently on 5xx responses?

# Plan

- Add a schema-equality assertion to the shadow traffic comparator.
- Raise shadow traffic to 50 percent for 24 hours.
- Profile the new client under the load test and find the p99 regression.
- Enable the feature flag in staging only.
- Document the rollback procedure before touching production.
