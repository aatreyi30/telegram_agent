# Make webhook ingestion idempotent

## Context
`POST /webhooks/stripe` is processed twice when Stripe retries after a timeout, producing
duplicate ledger rows. Retries carry the same `Stripe-Event-Id`.

## Acceptance criteria
1. Two requests with the same `Stripe-Event-Id` result in exactly one ledger row.
2. The second request returns 200 with body `{"status":"duplicate"}` and does not re-run
   any side effect.
3. Deduplication survives a process restart (persistent, not in-memory).
4. Dedup records older than 30 days are purged by an existing scheduled job.
5. A request with no `Stripe-Event-Id` header is rejected with 400 and is not processed.

## Out of scope
Signature verification. Other webhook providers. Ledger schema changes.

## Non-functional
Added latency under 15ms p99. No new infrastructure dependency.
