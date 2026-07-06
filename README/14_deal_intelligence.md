# Deal Intelligence Engine

Version: 1.0

Status: Engineering Specification

---

# Purpose

The Deal Intelligence Engine analyzes every discovered deal to understand what makes a deal successful.

It evaluates deal characteristics, historical performance, competitor usage and merchant behaviour to identify successful deal patterns.

The engine should answer:

- Which deals perform best?
- Why do they perform well?
- Which deals should be posted?
- Which deals should be ignored?
- What characteristics make a deal attractive?

The engine analyzes deals.

It does not create deals.

---

# Responsibilities

The Deal Intelligence Engine should:

- Build a profile for every discovered deal.
- Classify deal types.
- Evaluate deal quality.
- Compare similar deals.
- Track historical performance.
- Detect successful deal patterns.
- Detect poor performing deal patterns.
- Generate deal insights.
- Generate deal recommendations.

The engine must NOT:

- Scrape merchant websites.
- Calculate raw metrics.
- Publish posts.
- Generate Telegram captions.

---

# Business Questions

## Deal Quality

- Is this a good deal?
- Why is it a good deal?
- Is this the best observed price?

## Historical Comparison

- Have we seen this deal before?
- Was it cheaper previously?
- How often does this deal appear?

## Competitor Behaviour

- Which competitors posted this deal?
- How many competitors ignored it?
- Who posted first?
- Who achieved the highest engagement?

## Merchant Behaviour

- Does this merchant usually provide strong deals?
- Is this merchant improving?
- Is this discount unusual?

## User Decision

- Should we post this deal?
- Should we post immediately?
- Should we wait?
- Should we ignore it?

---

# Inputs

Knowledge Layer

- Deals
- Products
- Merchants
- Categories
- Historical Prices
- Historical Posts

Metrics Engine

- Deal Metrics
- Merchant Metrics
- Product Metrics
- Competitor Metrics

Discovery Engine

- Newly discovered products
- Newly discovered merchants

Reasoning Framework

Observation

↓

Evidence

↓

Reasoning

↓

Confidence

↓

Recommendation

↓

Expected Outcome

---

# Deal Profile

Every deal should maintain a structured profile.

Contains

Deal ID

Merchant

Product

Brand

Category

Current Price

MRP

Discount

Coupon

Offer Type

Effective Price

Availability

Historical Lowest Price

Historical Highest Price

Observed Since

Last Updated

Competitor Count

Performance Summary

Recommendation Status

---

# Deal Classification

Deals should be classified dynamically.

Examples include

- Loot Deal
- Standard Deal
- Coupon Deal
- Cashback Offer
- Bank Offer
- Exchange Offer
- Bundle Offer
- Limited Time Offer
- Flash Sale
- Buy One Get One
- Freebie Offer

New deal types should be discoverable through the Discovery Engine.

The list must never be hardcoded.

---

# Deal Analysis

Every deal should be analyzed from multiple perspectives.

## Price Analysis

Evaluate

Current Price

↓

Historical Price

↓

Price Trend

↓

Price Volatility

↓

Historical Lowest Price

↓

Historical Highest Price

Questions answered

- Is this price unusually low?
- Is this the lowest observed price?
- Is the price increasing?

---

## Discount Analysis

Evaluate

Average Discount

Median Discount

Discount Trend

Discount Distribution

Historical Discount

Questions answered

- Is this discount attractive?
- Is this discount common?
- Has this merchant offered better discounts before?

---

## Merchant Analysis

Evaluate

Merchant Performance

Merchant Trend

Merchant Consistency

Merchant Opportunity

Questions answered

- Is this merchant trusted?
- Does this merchant usually perform well?

---

## Competitor Analysis

Evaluate

Competitor Coverage

Posting Frequency

Posting Time

Engagement

Questions answered

- How many competitors posted this deal?
- Who posted first?
- Who achieved the best results?

---

## Product Analysis

Evaluate

Historical Performance

Category

Brand

Popularity

Historical Prices

Questions answered

- Is this product historically popular?
- Is demand increasing?

---

# Deal Quality Score

The engine should calculate a composite quality score.

Inputs may include

- Discount
- Historical Price
- Merchant Reputation
- Competitor Interest
- Product Popularity
- Historical Performance

The scoring formula should be configurable.

Individual component values should be available for inspection.

---

# Opportunity Detection

Detect situations such as

- Lowest observed price
- Rare discount
- Merchant promotion
- Competitor trend
- Seasonal opportunity
- Product resurgence
- Limited availability

Every opportunity should include supporting evidence.

---

# Pattern Detection

The engine should continuously learn patterns.

Examples

- Electronics under ₹500 perform well.
- Grocery bundles perform well on weekends.
- Bank offers increase engagement.
- Loot deals create higher forwarding behaviour.
- Flash sales require immediate posting.

Patterns should be based on historical evidence.

---

# Insights

Every insight must follow the same structure.

Observation

↓

Evidence

↓

Reasoning

↓

Confidence

Example

Observation

Electronics loot deals below ₹500 generated higher engagement.

Evidence

- Higher average views.
- Higher forwarding rate.
- Higher posting frequency among competitors.

Reasoning

Users responded positively to low-cost electronics offers during the observation period.

Confidence

High

---

# Recommendations

Every recommendation must include

Recommendation

Reason

Evidence

Confidence

Expected Outcome

Priority

Example

Recommendation

Publish this deal immediately.

Reason

Price is the lowest observed in the last 90 days and similar deals consistently performed well.

Evidence

- Historical price comparison.
- Competitor engagement.
- Merchant performance.

Confidence

High

Expected Outcome

Higher engagement than average electronics posts.

---

# Events Consumed

- DealExtracted
- DealUpdated
- MerchantUpdated
- ProductUpdated
- CompetitorUpdated
- DealMetricsUpdated

---

# Events Produced

- DealProfileUpdated
- DealPatternDetected
- DealOpportunityDetected
- DealInsightGenerated
- DealRecommendationGenerated

---

# User Interface

## Deal Dashboard

Show

- Total Deals
- Active Deals
- New Deals
- High Opportunity Deals
- Expiring Deals

---

## Deal Explorer

Filter by

- Merchant
- Category
- Deal Type
- Discount
- Price
- Opportunity Score
- Date

---

## Deal Detail Page

Display

- Timeline
- Historical Prices
- Discount History
- Competitor Activity
- Merchant Summary
- Product Summary
- Insights
- Recommendations

---

## Comparison View

Compare multiple deals using

- Price
- Discount
- Merchant
- Category
- Performance
- Opportunity

---

# API Responsibilities

Expose services such as

- Get Deal Profile
- Get Deal Timeline
- Get Historical Prices
- Get Deal Insights
- Get Deal Recommendations
- Compare Deals

---

# Failure Handling

If product information is unavailable

- Preserve verified information.
- Mark unavailable fields.
- Retry enrichment later.

If historical pricing is incomplete

- Generate analysis only from available observations.
- Never fabricate historical values.

If merchant validation fails

- Keep the deal.
- Flag the merchant relationship for review.

---

# Acceptance Criteria

The Deal Intelligence Engine is complete when

- Every discovered deal has a structured profile.
- Deal types are classified dynamically.
- Historical prices are preserved.
- Competitor activity is linked to deals.
- Deal opportunities are evidence-based.
- Recommendations always include reasoning and confidence.
- New deal types are learned automatically.
- Historical comparisons are available for every deal.

---

# Out of Scope

The Deal Intelligence Engine does not

- Scrape merchant websites.
- Collect Telegram messages.
- Calculate raw metrics.
- Publish Telegram posts.
- Generate captions.

Its responsibility is to transform structured deal data into actionable deal intelligence.