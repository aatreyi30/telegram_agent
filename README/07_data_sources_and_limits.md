# Data Sources and Limits

Version: 1.0

Status: Engineering Specification

---

# Purpose

This document defines every external and internal data source used by the platform.

It explicitly documents:

- Available data
- Missing data
- Collection methods
- Update frequency
- Reliability
- Technical limitations
- Confidence level
- Fallback behaviour

The platform must never assume data exists.

Every intelligence engine must operate only on verified data sources.

---

# Design Principle

The platform follows the rule:

Collect

↓

Validate

↓

Normalize

↓

Store

↓

Reason

↓

Recommend

Artificial Intelligence should never invent missing information.

---

# Data Source Categories

The platform uses multiple independent sources.

1. Telegram (Owned Channels)
2. Telegram (Competitor Channels)
3. Merchant Websites
4. Public Web
5. Historical Knowledge Base
6. User Configuration

Each source has different capabilities and limitations.

---

# Source 1 — Telegram (Owned Channels)

Purpose

Collect first-party channel data for channels managed by the organization.

Collection Method

MTProto Client API

Required Permissions

Channel administrator with statistics access (where applicable).

Available Data

Channel metadata

Posts

Media

Views

Reactions

Forwards

Publishing timestamps

Historical message history

Channel statistics (where supported)

Audience analytics

Top active hours

Growth graphs

Traffic source graphs

Languages

Notification statistics

Historical post performance

Update Frequency

Near real-time for new posts.

Scheduled refresh for analytics (e.g. every hour).

Confidence

High

Source of Truth

Telegram

Limitations

Statistics are only available for channels where the authenticated account has sufficient administrative permissions. :contentReference[oaicite:0]{index=0}

---

# Source 2 — Telegram (Competitor Channels)

Purpose

Observe public competitor behaviour.

Collection Method

MTProto Client API using an authenticated user account.

Required Access

Public channel or a channel the authenticated account can access.

Available Data

Channel metadata

Posts

Media

Captions

Links

Posting timestamps

Public view counts

Reactions (when visible)

Forward counts (when visible)

Pinned messages

Message edits

Deleted messages (if detected during polling)

Unavailable Data

Subscriber growth

Audience demographics

Notification settings

Internal analytics

Traffic sources

Retention

Follower acquisition sources

These statistics are not available because Telegram only exposes detailed analytics to channel administrators. :contentReference[oaicite:1]{index=1}

Strategy

Build competitor intelligence from observable behaviour rather than private analytics.

---

# Source 3 — Merchant Websites

Purpose

Verify and enrich deal information.

Examples

Amazon

Flipkart

Ajio

Myntra

Nykaa

Croma

Purpose

Validate:

Current price

Availability

Coupon

Stock status

Product title

Images

Category

Brand

Historical price (when available)

Collection Method

Site-specific scraper or API where available.

Update Frequency

On discovery and periodic refresh.

Confidence

High when data matches the live product page.

Fallback

Mark as stale if scraping fails.

---

# Source 4 — Public Web

Purpose

Discover competitors before Telegram monitoring begins.

Pipeline

Organization

↓

Official Website

↓

Business Category

↓

Known Competitors

↓

Official Websites

↓

Official Telegram Channels

↓

Validation

↓

Monitoring

Example - just an example don't hardcode this 

GrabOn

↓

Competitors discovered

DesiDime

Zoutons

CouponzGuru

CashKaro

↓

Find each brand's official Telegram channel

↓

Validate ownership

↓

Begin monitoring

This step should not rely on a hardcoded competitor list. It should use search, structured business information, and verification rules.

---

# Competitor Discovery Strategy

The system should identify business competitors before identifying Telegram competitors.

Process

1. Identify the organization's business domain.
2. Discover major competitors within that domain.
3. Validate that each competitor is relevant.
4. Search for official Telegram channels.
5. Verify authenticity using signals such as:
   - Website links to Telegram
   - Telegram links from official social profiles
   - Consistent branding and naming
6. Begin monitoring only validated channels.

If no official Telegram channel exists, the competitor should remain in the business graph but be marked as "No Telegram Presence".

---

# Source 5 — Historical Knowledge Base

Purpose

Provide long-term memory.

Contains

Posts

Deals

Merchants

Competitors

Predictions

Recommendations

Performance

Learning records

Retention

Minimum 12 months.

Historical data should never be overwritten.

---

# Source 6 — User Configuration

Purpose

Allow manual overrides.

Examples

Add competitor.

Remove competitor.

Approve discovered competitor.

Blacklist merchants.

Preferred posting hours.

Automation rules.

Manual configuration should complement—not replace—automatic discovery.

---

# Data Reliability Levels

Level 1 — Verified

Directly collected from Telegram or merchant websites.

Level 2 — Derived

Calculated from verified data.

Examples

Posting frequency

Average discount

Merchant share

Category distribution

Level 3 — Inferred

Produced by reasoning engines.

Examples

Competitor similarity

Content strategy

Trend explanations

Every inferred insight must include confidence.

---

# Collection Schedule

Owned channel posts:
- Event-driven + scheduled sync

Owned channel analytics:
- Hourly (configurable)

Competitor channels:
- Incremental polling every 15–60 minutes (configurable based on channel activity)

Merchant validation:
- On new deal discovery + scheduled refresh

Competitor discovery:
- Weekly by default, with manual refresh available

Knowledge base rebuild:
- Incremental after every successful collection

Learning cycle:
- Daily and weekly

---

# Failure Handling

Telegram unavailable

Action

Retry with exponential backoff.

Merchant unavailable

Action

Keep last verified data and mark stale.

Competitor renamed

Action

Attempt username resolution, then manual review.

Official Telegram channel not found

Action

Continue tracking the competitor as a business entity and retry discovery periodically.

Price mismatch

Action

Flag for review rather than overwriting verified historical data.

---

# Acceptance Criteria

The system must clearly distinguish:

- Data collected directly from Telegram.
- Data collected from merchant websites.
- Data inferred through reasoning.
- Data unavailable due to platform limitations.

No recommendation may rely on fabricated or assumed data.

Every intelligence engine must declare which data sources it depends on before implementation.