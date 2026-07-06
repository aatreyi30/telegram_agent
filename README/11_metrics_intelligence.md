# Metrics Engine

Version: 1.0

Status: Engineering Specification

---

# Purpose

The Metrics Engine transforms raw facts stored in the Knowledge Layer into measurable business metrics.

Metrics are numerical representations of historical or current performance.

The Metrics Engine does not generate insights, recommendations, or strategies.

Its responsibility is only to calculate and maintain accurate metrics.

---

# Responsibilities

The Metrics Engine should:

- Calculate business metrics.
- Maintain historical metric values.
- Refresh metrics when source data changes.
- Support real-time and scheduled recalculations.
- Provide metrics to all downstream intelligence engines.

The Metrics Engine must NOT:

- Explain why a metric changed.
- Recommend actions.
- Generate content.
- Predict future performance.

---

# Design Principles

Metrics should be:

- Deterministic
- Reproducible
- Explainable
- Versioned
- Historical

Every metric should be traceable back to its underlying data.

---

# Metric Lifecycle

Every metric follows the same process.

```
Knowledge Layer

↓

Metric Calculation

↓

Validation

↓

Storage

↓

Metric Event

↓

Intelligence Engines
```

---

# Metric Structure

Every metric should contain:

Metric Name

Description

Value

Unit

Calculation Timestamp

Calculation Version

Source Data

Confidence (if applicable)

Historical Values

---

# Metric Categories

The platform groups metrics into logical families.

---

# Channel Metrics

Purpose

Measure overall channel performance.

Examples

- Total Subscribers
- Subscriber Growth
- Daily Growth
- Weekly Growth
- Monthly Growth
- Net Growth
- Posting Frequency
- Posts Per Day
- Average Views
- Median Views
- Average Reactions
- Average Forwards
- Engagement Rate
- Reach Rate
- Posting Consistency
- View Velocity

---

# Content Metrics

Purpose

Understand publishing behaviour.

Examples

- Images Posted
- Videos Posted
- Text Posts
- Polls
- Albums
- Average Caption Length
- Emoji Usage
- Hashtag Usage
- Link Usage
- Call-To-Action Frequency
- Media Distribution

---

# Deal Metrics

Purpose

Measure deal quality.

Examples

- Average Discount
- Median Discount
- Maximum Discount
- Minimum Discount
- Effective Price
- MRP Distribution
- Discount Distribution
- Coupon Usage
- Cashback Usage
- Bank Offer Usage
- Loot Deal Frequency
- Flash Sale Frequency
- Deal Lifetime
- Price Drop Percentage

---

# Merchant Metrics

Purpose

Measure merchant performance.

Examples

- Merchant Share
- Merchant Growth
- Merchant Posting Frequency
- Average Merchant Discount
- Merchant Engagement
- Merchant Trend
- Merchant Visibility
- Merchant Diversity
- Merchant Win Rate
- Merchant Retention

---

# Product Metrics

Purpose

Track product-level performance.

Examples

- Product Mentions
- Product Growth
- Historical Price
- Lowest Observed Price
- Highest Observed Price
- Average Discount
- Merchant Availability
- Engagement
- Trend

---

# Category Metrics

Purpose

Understand category performance.

Examples

- Category Distribution
- Category Growth
- Category Engagement
- Category Diversity
- Category Trend
- Seasonal Performance
- Posting Frequency
- Merchant Distribution

Categories are dynamic and should never be hardcoded.

---

# Competitor Metrics

Purpose

Measure competitor behaviour.

Examples

- Posts Per Day
- Posts Per Week
- Active Hours
- Active Days
- Posting Consistency
- Merchant Distribution
- Category Distribution
- Deal Distribution
- Offer Distribution
- Average Discount
- Average Price
- Caption Length
- Media Mix
- Link Usage
- Hashtag Usage
- Posting Velocity

No private Telegram analytics should be inferred.

Metrics should only use observable public data.

---

# Audience Metrics

Purpose

Measure audience behaviour for owned channels.

Examples

- Audience Growth
- Active Hours
- Peak Days
- View Distribution
- Engagement Rate
- Reach
- Returning Engagement
- Growth Trend

Only use analytics available for channels the organization manages.

---

# Automation Metrics

Purpose

Evaluate automation effectiveness.

Examples

- Scheduled Posts
- Published Posts
- Failed Posts
- Approval Time
- Average Publish Delay
- Retry Count

---

# Platform Metrics

Purpose

Monitor platform health.

Examples

- Collection Jobs
- Collection Failures
- Processing Time
- Queue Length
- Failed Normalizations
- Average Refresh Time
- Event Processing Time

---

# Metric Storage

Every metric should maintain history.

Example

```
Average Discount

2026-07-01

61%

↓

2026-07-02

63%

↓

2026-07-03

59%
```

Historical values should never be overwritten.

---

# Recalculation Triggers

Metrics should be recalculated when:

- A new post is normalized.
- A deal changes.
- Merchant data changes.
- Analytics refresh.
- Competitor data updates.
- Historical rebuild is requested.

Avoid recalculating unrelated metrics.

---

# Events Consumed

- PostNormalized
- DealUpdated
- MerchantUpdated
- AnalyticsUpdated
- CompetitorUpdated
- ProductUpdated

---

# Events Produced

- ChannelMetricsUpdated
- MerchantMetricsUpdated
- DealMetricsUpdated
- CategoryMetricsUpdated
- CompetitorMetricsUpdated
- AudienceMetricsUpdated

---

# API Responsibilities

The Metrics Engine should expose metrics through internal services.

Examples

Get Channel Metrics

Get Merchant Metrics

Get Competitor Metrics

Get Category Metrics

Get Product Metrics

Get Deal Metrics

Intelligence engines must request metrics instead of recalculating them.

---

# Failure Handling

If source data is unavailable:

- Preserve previous metrics.
- Mark metrics as stale.
- Log recalculation failures.
- Retry automatically.

Do not delete historical metrics.

---

# Acceptance Criteria

The Metrics Engine is complete when:

- Metrics are calculated from the Knowledge Layer only.
- Historical metric values are preserved.
- Metrics update automatically after relevant data changes.
- Duplicate calculations are avoided.
- Every metric is traceable to its source data.
- Downstream intelligence engines consume metrics instead of performing their own calculations.

---

# Out of Scope

The Metrics Engine does not:

- Explain metric changes.
- Generate insights.
- Recommend actions.
- Predict future performance.
- Produce AI-generated content.

It exists solely to provide accurate, reusable measurements for the rest of the platform.