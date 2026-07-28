# Spec — One slot = one post. The agent plans every post, and the schedule is real.

## The reported defect

> "I want the agent to genuinely plan the windows, each post, and act on it — not this
> vague windows ... it is only planning 1 brand for a 4-5 hr slot. there should be a mix."

## Root cause — two defects, both verified in code

**BUG 1 — the plan schema cannot express a mix. (`ai/prompts/daily_plan.py:141`)**
The emitted slot object is one-per-*window*:
```
{"type":"single|collection","window_ist":"HH:MM-HH:MM","count":<int>,
 "theme":"<category>","merchant":"<merchant>","max_price":...,"min_price":...}
```
`merchant`, `theme` and `type` are **scalars**, alongside a `count`. So a window carrying
5 posts is by construction 5 posts of the *same* merchant, same category, same type. The
model is not being lazy — the JSON shape gives it no way to say anything else. Every
downstream diversity repair is therefore fighting the schema instead of the model.

**BUG 2 — the window is a label, not a schedule. (`services/generation/jit_fill.py:63
_expand_slots` + `:55 _window_start`)**
`_window_start` regexes only the FIRST `HH:MM` out of `"09:00-12:00"`; the end time is
parsed and discarded. `_expand_slots` then fires the window's posts at
`SPACING_MIN = 2` minute intervals **from the window start**. A 5-post 09:00-12:00 window
becomes 09:00, 09:02, 09:04, 09:06, 09:08 — an 8-minute burst, then three hours of silence.
Confirmed by the clustered `generated_at` values in `generated_posts`.

Together these are the whole reported symptom: one brand, dumped all at once, then nothing.

## The shape we want

**One slot object = one post.** The agent decides, per post: when it fires, what merchant,
what category, what type, what price intent, and why — and the executor fires it at that
time. Nothing else in the pipeline changes shape.

## Acceptance criteria

**AC1 — per-post plan schema.** The daily-plan JSON contract becomes one object per post:
```
{"type":"single|collection","time_ist":"HH:MM","theme":"<category>",
 "merchant":"<merchant>","max_price":<int|null>,"min_price":<int|null>,"why":"..."}
```
`window_ist`/`count` are no longer the emitted shape. The prompt states plainly that each
object is exactly one post at exactly that minute, that consecutive posts must not repeat
the same merchant or the same category when the day's available deals offer an
alternative, and that the day's posts must spread across each posting window rather than
bunch at its start. `why` stays per-post and must cite a real number (the existing
factcheck already verifies cited numbers — do not weaken it).

**AC2 — backward compatibility, not a migration.** Plans already stored with
`window_ist` + `count` (and any model reply that falls back to that shape) must still
execute. `_expand_slots` accepts both:
- a slot carrying `time_ist` -> exactly one post at that IST minute;
- a legacy slot carrying `window_ist` + `count` -> `count` posts **spread evenly across the
  parsed window span** (start..end), not stacked at the start.
This means `_window_start` gains an end-parse (or is replaced by a span parser). A window
with an unparseable or inverted span keeps the current safe behaviour of skipping.
`SPACING_MIN` stops being the spacing rule and is only a **minimum** gap enforced between
consecutive posts so two never collide on the same minute.

**AC3 — the executor honours per-post intent.** `fill_due_slots` reads `merchant`,
`theme`, `type` and the price bounds off the individual slot (it already does — verify no
code path re-derives them from a window-level object), and each generated post's
`format_meta.slot` records the per-post intent so plan-vs-actual stays auditable.

**AC4 — plan-time adjacency repair, both dimensions.** The existing
`ai/planner.py:33 _repair_merchant_diversity` currently balances merchants only. With
one-slot-per-post it must also ensure two chronologically adjacent posts don't share a
`theme` when the day's available deals offer another category, reassigning the fewest
slots possible and rewriting a reassigned slot's `why` so the prose can't contradict the
reassignment. Rename it to reflect that it balances both dimensions. No-ops with fewer
than 2 available merchants/categories respectively. It must operate on chronological
order, not on the old window grouping.

**AC5 — count reconciliation still holds.** `services/generation/ai_execution.py` clamps
and rescales the plan's post counts to the recent-cadence bound. With one-object-per-post,
"rescale counts" becomes "drop or duplicate whole slots" — it must keep the reconciled
total exactly, keep posts chronologically ordered, and preserve the type mix within the
existing `_MIN_TYPE_SHARE` floor. Records the same `plan_clamped` flag it does today.

**AC6 — the fallback plan matches the new shape.** `ai/planner.py:314 _fallback_day_plan`
(the deterministic plan used when the AI is unavailable or unparseable) emits per-post
slots with spread times and a rotating merchant/category — so an AI outage still produces
a properly-mixed, properly-spread day rather than the old bursty shape.

**AC7 — tests that would have caught both bugs.**
- A 5-post 09:00-12:00 legacy window expands to 5 times spread across the full span, with
  the first at/after 09:00 and the last at/before 12:00, no two on the same minute — and
  explicitly asserts they are NOT 2 minutes apart.
- A per-post plan with explicit `time_ist` values fires at exactly those minutes.
- Adjacency repair breaks a run of identical themes and a run of identical merchants.
- Count reconciliation preserves the exact target total and chronological order.

**AC8 — gate green.** `loops/01-ship/scripts/gate.sh` exits 0. No test skipped or deleted.

## Out of scope
The merchant allowlist (already correct in three places), the loot board's internal
round-robin, and `available_deals` menu diversification. Do not touch `next/`.
