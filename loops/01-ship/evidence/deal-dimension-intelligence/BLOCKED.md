# RESOLVED — the trip-3 blocker is fixed (user authorised the fix)

The blocker below was fixed after the user reviewed it and said to proceed. Kept for the
audit trail, with the outcome recorded.

## The blocker (was)

`_feed_pairs()` computed `(merchant, category) -> live deal count`, and all three call sites
threw the count away with `set(...)`. Two symptoms:

- **S1-1** reconciliation invented unstocked pairings (`myntra + electronics`, 0 deals) and its
  guard derived the valid-pair list *after* appending them, so they whitelisted themselves.
- **S1-2** allocation was stock-blind: a 12-post day put **3 slots on `amazon+beauty`, a pairing
  with 1 deal in the whole feed**; 42% of slots sat on pairings with <=2 deals. Those can't fill
  on-theme, so `jit_fill` broadened — the user's original complaint, one layer up.

## The fix

The counts are now threaded through instead of discarded. `available_pairs` accepts the counts
dict (its keys satisfy the existing membership checks, so it's a non-breaking widening); the
repair treats a pairing already holding as many slots as it has deals as a violation eligible
for reassignment; and `generate_day_plan` carries `feed_pairs` forward through `persist_ai_plan`
-> `_rescale_slot_counts` -> `_reconcile_per_post_slots`, so a duplicate is built as a real
feed-stocked PAIR rather than by rotating merchant and theme through two independent pools.
Also fixed S3-1: a merchant *at* its cap (not merely repeating the prior slot) never triggered
the pair-swap fallback, which is why the cap went soft.

12-post day on the live cross-tab: `amazon+beauty` 3 slots -> 1 (stock 1);
`amazon+electronics` 0 -> 2 (stock 28). No pairing exceeds its stock.

## Verified independently (orchestrator, by execution — not from the agent's report)

Live feed (18 pairs) at targets 3/7/12/17/23/31 and sparse feed (4 pairs) at 5/12/23/31:
exact post counts, **zero** off-feed pairings, **zero** adjacent same-merchant, **zero**
adjacent same-theme, unique fire minutes throughout.

Mutation-confirmed: M5 (drop `available_pairs=`), M11 (`_pair_sequence` alphabetical instead of
stock-depth), S3-1 (drop the cap check) and S1-2 (revert to `set(...)`) each now fail a test.

## Known, accepted limitation — stated rather than hidden

The allocator is a single greedy forward pass, not a solver. On a **sparse** feed it can put one
or two slots over a pairing's stock once the day's post count approaches the feed's total:

```
target as % of total feed stock:   <=87%  -> 0 slots over stock
                                     88%  -> 1
                                    100%  -> 2
```

Not reachable in production: the live feed holds ~234 deals and a day is 12-35 posts (~15% of
stock). When it does occur the blast radius is one slot broadening at fill time, and deal-id
dedup still prevents the same deal being posted twice. Fixing it properly means replacing the
greedy pass with an allocator that balances against remaining stock globally — worth doing only
if real days ever approach feed exhaustion.

## Still open — decisions, not code

- Publishing is hard-gated (`_check_and_publish` returns `False`); nothing reaches the channel.
- Owned vs test channel split-brain (gap analysis §4.1) — needs a call on the source of truth.
- `/r/{id}` click tracker (§4.3) — the only route to real CTR/revenue attribution.
