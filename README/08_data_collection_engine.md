# Data Collection Engine

Version: 1.0

Status: Engineering Specification

---

# Purpose

The Data Collection Engine is responsible for reliably collecting all raw information required by the platform.

It is the only component allowed to communicate directly with external data sources.

No intelligence engine should call Telegram, merchant websites, or external services directly.

Every other module must consume data from the Knowledge Layer.

---

# Responsibilities

The Data Collection Engine is responsible for:

- Collecting Telegram data for owned channels
- Collecting public competitor channel data
- Collecting merchant data
- Discovering competitors
- Detecting changes
- Scheduling data refreshes
- Deduplicating collected data
- Recording collection metadata
- Handling failures and retries

It is NOT responsible for:

- AI reasoning
- Recommendations
- Content generation
- Strategy
- Dashboard calculations

---

# Design Principles

1. Collect first, process later.
2. Never modify raw collected data.
3. Every collection operation must be traceable.
4. Collection failures must never corrupt existing data.
5. Incremental collection should be preferred over full rescans.
6. Every collected record must include a collection timestamp.

---

# Data Sources

The engine collects data from:

- Telegram (Owned Channels)
- Telegram (Competitor Channels)
- Merchant Websites
- Public Web (Competitor Discovery)

Each source has an independent collector.

Collectors should not depend on each other.

---

# Collection Pipeline

Every collector follows the same lifecycle.

```
Scheduler/Event

↓

Fetch Data

↓

Validate Response

↓

Store Raw Snapshot

↓

Normalize

↓

Store Structured Data

↓

Update Knowledge Layer

↓

Emit Collection Event
```

No step should be skipped.

---

# Collection Types

## Initial Collection

Purpose

Collect historical information when a channel is connected for the first time.

Characteristics

- Long-running
- Historical
- Can take several minutes
- Resumable
- Idempotent

Collected Data

- Channel metadata
- Historical posts (target: up to 12 months where available)
- Media
- Analytics (where available)
- Audience statistics (where available)

---

## Incremental Collection

Purpose

Collect only newly available information.

Characteristics

- Fast
- Frequent
- Lightweight

Collected Data

- New posts
- Edited posts
- Deleted posts (if detectable)
- Updated analytics
- New reactions
- Updated view counts (where applicable)

---

## Manual Collection

Triggered by the user.

Examples

- Refresh competitor
- Refresh merchant
- Rebuild analytics
- Rescan channel

Manual jobs should enter the same queue as scheduled jobs.

---

# Owned Channel Collector

Purpose

Collect first-party data.

Required Data

- Channel metadata
- Posts
- Media
- Analytics
- Audience statistics
- Message statistics (where available)

Collection Strategy

- Initial historical sync
- Incremental sync
- Event-driven updates where possible
- Scheduled reconciliation to detect missed changes

Source of Truth

Telegram

---

# Competitor Channel Collector

Purpose

Observe public competitor behaviour.

Required Data

- Channel metadata
- Public posts
- Media
- Captions
- Links
- Visible view counts
- Visible reactions
- Posting timestamps

Do NOT attempt to collect unavailable private analytics.

The collector should only store observable information.

---

# Merchant Collector

Purpose

Enrich deal information.

Collected Data

- Product title
- Current price
- MRP
- Availability
- Images
- Category
- Brand
- Product URL
- Last updated timestamp

Collection Strategy

Run when:

- New product discovered
- Existing data expires
- Manual refresh requested

---

# Competitor Discovery Collector

Purpose

Identify real business competitors before monitoring Telegram channels.

Pipeline

Organization

↓

Business Domain

↓

Discover Business Competitors

↓

Validate Competitors

↓

Find Official Website

↓

Find Official Telegram Channel

↓

Validate Telegram Channel

↓

Register Competitor

Discovery should be repeatable.

New competitors should be added automatically after validation.

---

# Scheduler

The scheduler is responsible for deciding when collection jobs execute.

Suggested frequencies (must remain configurable):

Owned channel sync:
- Near real-time for new posts (if supported)
- Scheduled reconciliation

Owned channel analytics:
- Hourly

Competitor monitoring:
- Every 15–60 minutes based on channel activity

Merchant validation:
- On discovery + scheduled refresh

Competitor discovery:
- Weekly

Learning refresh:
- Daily

---

# Queue Management

Every collection request becomes a job.

Job lifecycle:

```
Queued

↓

Running

↓

Succeeded

or

Failed

↓

Retry (if eligible)

↓

Completed
```

Every job should have:

- Unique ID
- Type
- Priority
- Retry count
- Status
- Start time
- End time
- Error message (if failed)

---

# Deduplication

Before storing any collected object:

Check whether it already exists.

If unchanged:

- Update last seen timestamp only.

If changed:

- Store new version.
- Preserve historical versions where required.

Never overwrite historical records without version tracking.

---

# Change Detection

The engine should detect meaningful changes.

Examples

Posts:
- New
- Edited
- Deleted (where detectable)

Merchant:
- Price changed
- Availability changed

Competitor:
- New posting pattern
- New merchant observed
- New category observed

Channel:
- Metadata updated

Detected changes should emit events for downstream processing.

---

# Events

After successful collection, emit structured events.

Examples

- PostCollected
- PostUpdated
- CompetitorUpdated
- MerchantUpdated
- AnalyticsUpdated
- DiscoveryCompleted

Intelligence engines subscribe to these events instead of polling external systems.

---

# Error Handling

Possible failures

Telegram unavailable

Merchant unavailable

Rate limit reached

Network timeout

Parsing failure

Authentication expired

Handling Rules

- Retry transient failures.
- Log permanent failures.
- Preserve existing verified data.
- Never insert partial records without marking them incomplete.
- Surface persistent failures to administrators.

---

# Observability

Every collection job must record:

- Source
- Start time
- End time
- Duration
- Records processed
- Records added
- Records updated
- Records skipped
- Errors
- Retry count

This information powers operational dashboards and troubleshooting.

---

# Security

- Store credentials securely.
- Encrypt sensitive tokens.
- Apply least-privilege access.
- Audit all authentication changes.
- Never expose secrets in logs.

---

# Acceptance Criteria

The Data Collection Engine is considered complete when:

- Historical channel data can be collected reliably.
- Incremental updates do not duplicate records.
- Competitor channels are monitored automatically.
- Merchant information is refreshed correctly.
- Collection failures do not corrupt stored data.
- Every collected record is traceable to its source.
- Downstream intelligence engines receive events after successful collection.
- Schedules and retry behaviour are configurable without code changes.