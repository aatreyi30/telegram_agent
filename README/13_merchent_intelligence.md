# Merchant Intelligence Engine

Version: 1.0

Status: Engineering Specification

---

# Purpose

The Merchant Intelligence Engine analyzes merchant performance across owned channels and competitor channels to help users make better posting decisions.

It transforms merchant-related facts and metrics into actionable business intelligence.

The engine should answer:

- Which merchants perform best?
- Which merchants are growing?
- Which merchants are declining?
- Which merchants are underutilized?
- Which merchants should be prioritized?
- Why?

---

# Responsibilities

The Merchant Intelligence Engine should:

- Build merchant profiles.
- Monitor merchant performance.
- Compare merchant performance over time.
- Compare merchants across competitors.
- Detect merchant trends.
- Detect merchant opportunities.
- Generate merchant insights.
- Generate merchant recommendations.

The engine must NOT:

- Collect merchant data.
- Scrape merchant websites.
- Calculate raw metrics.
- Generate Telegram content.

---

# Business Questions

The engine should answer questions such as:

Performance

- Which merchant generated the highest engagement this week?
- Which merchant has the highest average views?
- Which merchant has the highest posting frequency?

Growth

- Which merchants are growing?
- Which merchants are declining?
- Which merchants are becoming more popular?

Competition

- Which merchants are competitors posting most frequently?
- Which merchants are we ignoring?
- Which merchants are oversaturated?

Opportunity

- Which merchants should we post tomorrow?
- Which merchants are trending but not yet used?
- Which merchants deserve more attention?

Seasonality

- Which merchants perform better during sales?
- Which merchants perform well during weekends?
- Which merchants perform well during festivals?

---

# Inputs

The engine consumes information from:

Knowledge Layer

- Merchant entities
- Posts
- Deals
- Products
- Categories
- Competitors

Metrics Engine

- Merchant metrics
- Channel metrics
- Category metrics
- Deal metrics

Discovery Engine

- Newly discovered merchants
- Brand updates

No direct Telegram API calls are allowed.

---

# Merchant Profile

Every merchant should maintain a continuously updated profile.

Example

Merchant Name

Merchant Type

Official Website

Business Category

Products

Categories

Historical Performance

Historical Discounts

Posting Frequency

Competitor Presence

Trend

Opportunity Score

Risk Score

Confidence

Last Updated

---

# Merchant Lifecycle

Every merchant follows the same lifecycle.

```
Discovered

↓

Validated

↓

Profile Created

↓

Performance Measured

↓

Trend Calculated

↓

Recommendations Generated

↓

Continuously Updated
```

---

# Merchant Analysis

The engine should analyze:

## Performance

Examples

Average views

Average engagement

Average reactions

Average forwards

Average deal performance

Average click-through proxy (if available)

---

## Activity

Examples

Posting frequency

Days active

Weeks active

Months active

Posting consistency

---

## Discount Behaviour

Examples

Average discount

Median discount

Highest discount

Lowest discount

Discount volatility

---

## Pricing Behaviour

Examples

Average selling price

Median selling price

Price distribution

Lowest observed price

Highest observed price

Historical price movement

---

## Category Distribution

Examples

Electronics

Fashion

Travel

Finance

OTT

Beauty

Groceries

No categories should be hardcoded.

---

## Deal Type Distribution

Examples

Loot Deals

Flash Sales

Coupons

Bank Offers

Cashback

Exchange Offers

Bundle Deals

---

## Competitor Usage

For each merchant calculate:

Number of competitors posting the merchant

Posting frequency

Average engagement

Growth trend

Preferred deal types

Preferred posting times

---

## Historical Trends

Track:

7 Days

30 Days

90 Days

180 Days

365 Days

Never overwrite history.

---

# Merchant Scores

The engine should calculate composite scores.

Examples

Performance Score

Popularity Score

Trend Score

Opportunity Score

Consistency Score

Competition Score

Confidence Score

Scores should always reference measurable metrics.

---

# Opportunity Detection

The engine should automatically identify opportunities.

Examples

Merchant trending across competitors.

Merchant underutilized in our channel.

Merchant engagement increasing.

Merchant discount quality improving.

Merchant appearing in new categories.

Merchant becoming seasonal.

Every opportunity must include supporting evidence.

---

# Merchant Comparison

Allow comparisons such as:

Merchant vs Merchant

Amazon vs Flipkart

Ajio vs Myntra

Nykaa vs Purplle

Organization vs Competitors

Our Amazon performance

↓

Competitor Amazon performance

Time Comparison

Amazon

This Week

↓

Last Week

↓

Last Month

---

# Merchant Insights

Insights should explain observations.

Example

Observation

Amazon engagement increased 18%.

Reason

Electronics loot deals increased.

Supporting Evidence

- 42% more electronics posts.
- Average discount increased.
- Competitors also increased Amazon posting.

Confidence

High

---

# Merchant Recommendations

Recommendations must always include:

Recommendation

Reason

Evidence

Confidence

Expected Outcome

Priority

Example

Recommendation

Increase Amazon loot deals this weekend.

Reason

Competitors achieved significantly higher engagement using Amazon electronics offers.

Evidence

- Higher average engagement.
- Higher posting frequency.
- Increased discount quality.

Confidence

High

Expected Outcome

Higher reach and engagement.

---

# Events Consumed

- MerchantDiscovered
- MerchantUpdated
- DealUpdated
- ProductUpdated
- CompetitorUpdated
- ChannelMetricsUpdated
- MerchantMetricsUpdated

---

# Events Produced

- MerchantProfileUpdated
- MerchantTrendDetected
- MerchantOpportunityDetected
- MerchantRecommendationGenerated
- MerchantInsightGenerated

---

# Failure Handling

If merchant data is incomplete:

- Preserve verified information.
- Mark unknown fields explicitly.
- Do not estimate missing values.
- Continue updating available information.

If conflicting merchant identities are detected:

- Flag for manual review.
- Preserve existing relationships until resolved.

---

# User Interface

The Merchant Intelligence page should provide:

## Merchant Overview

- Total merchants
- Active merchants
- New merchants
- Trending merchants

## Merchant Directory

Searchable list of merchants with:

- Performance
- Trend
- Categories
- Opportunity score
- Last activity

## Merchant Detail Page

Each merchant should display:

- Historical performance
- Category breakdown
- Deal breakdown
- Competitor usage
- Timeline
- Price history
- Discount history
- Recommendations
- Related products

## Comparison View

Compare multiple merchants side by side.

## Opportunity View

Show merchants ranked by opportunity score with evidence.

---

# API Responsibilities

The engine should expose internal services such as:

- Get Merchant Profile
- Get Merchant Timeline
- Get Merchant Trends
- Get Merchant Comparison
- Get Merchant Opportunities
- Get Merchant Recommendations

---

# Acceptance Criteria

The Merchant Intelligence Engine is complete when:

- Every discovered merchant has a continuously updated profile.
- Merchant performance is calculated using Metrics Engine outputs.
- Historical trends are preserved.
- Competitor merchant activity is analyzed.
- Opportunity detection is evidence-based.
- Recommendations always include reasoning and confidence.
- No hardcoded merchant list exists.
- New merchants are incorporated automatically through the Discovery Engine.

---

# Out of Scope

The Merchant Intelligence Engine does not:

- Scrape merchant websites.
- Normalize Telegram posts.
- Calculate raw metrics.
- Generate Telegram content.
- Execute automated posting.

Its sole responsibility is to transform merchant-related facts and metrics into actionable merchant intelligence.