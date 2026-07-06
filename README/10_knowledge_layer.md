# Knowledge Layer

Version: 1.0

Status: Engineering Specification

---

# Purpose

The Knowledge Layer is the central source of truth for the entire platform.

Every intelligence engine must read from the Knowledge Layer instead of directly querying Telegram, merchant websites, or external services.

The Knowledge Layer stores facts.

It does not generate opinions.

It does not perform reasoning.

Its responsibility is to organize information in a way that every downstream engine can reuse consistently.

---

# Objectives

The Knowledge Layer should:

- Eliminate duplicate data.
- Maintain relationships between entities.
- Preserve historical information.
- Enable efficient querying.
- Support continuous learning.
- Act as the foundation for every intelligence engine.

---

# Design Principles

## Single Source of Truth

Every business entity must exist only once.

Example

Merchant

Amazon

should exist as one merchant entity.

Every post, product, deal and competitor should reference the same merchant.

---

## Relationships Over Duplication

The platform should connect entities instead of copying data.

Example

```
Organization

↓

Channel

↓

Post

↓

Deal

↓

Merchant

↓

Product
```

The same product should never be recreated for every post.

---

## Historical First

Nothing should overwrite historical information.

Instead of

```
Price

699
```

Store

```
699

↓

599

↓

549

↓

499
```

Every change becomes part of history.

---

## Event Driven

The Knowledge Layer updates only when events occur.

Examples

PostNormalized

MerchantDetected

PriceChanged

DealUpdated

CompetitorDiscovered

AnalyticsUpdated

No intelligence engine should directly modify stored knowledge.

---

# Core Business Objects

The Knowledge Layer stores the following entities.

---

## Organization

Represents one customer account.

Relationships

```
Organization

├── Users

├── Channels

├── Reports

├── Automation

└── Knowledge
```

---

## Channel

Represents one Telegram channel.

Contains

Metadata

Settings

Analytics

Audience

Posts

Competitors

Automation

Learning History

---

## Post

Represents one Telegram message.

Contains

Text

Media

Views

Reactions

Links

Timestamp

Language

Relationships

Deal

Merchant

Category

Product

Performance

---

## Deal

Represents one commercial offer.

Contains

Current Price

MRP

Discount

Coupon

Bank Offer

Availability

Status

Relationships

Merchant

Product

Category

Posts

---

## Merchant

Represents a marketplace or brand.

Contains

Merchant Name

Website

Marketplace Type

Historical Performance

Historical Discounts

Trend

Relationships

Deals

Products

Competitors

Channels

---

## Product

Contains

Product Name

Brand

Merchant

Historical Prices

Current Price

Category

Performance

Relationships

Deals

Posts

Merchants

---

## Category

Contains

Category Name

Parent Category

Subcategory

Relationships

Products

Deals

Merchants

Posts

Competitors

---

## Competitor

Represents a business competitor.

Not simply a Telegram channel.

Contains

Business Name

Official Website

Industry

Telegram Channels

Similarity Score

Historical Performance

Monitoring Status

---

## Competitor Channel

Represents one Telegram channel belonging to a competitor.

Contains

Channel Metadata

Posts

Posting Behaviour

Merchant Distribution

Category Distribution

Content Behaviour

Media Behaviour

Historical Snapshots

A competitor may own multiple Telegram channels.

---

## Analytics

Stores measured facts.

Examples

Views

Subscribers

CTR

Reach

Posting Frequency

Engagement

Analytics should never contain recommendations.

---

## Insight

Represents interpreted information.

Example

Views decreased because:

- Electronics posting frequency dropped.
- Competitor activity increased.
- Evening posting window was missed.

Insights always reference supporting evidence.

---

## Recommendation

Represents a suggested action.

Contains

Action

Reason

Evidence

Confidence

Expected Outcome

Source Intelligence Engine

Recommendations never exist without supporting evidence.

---

## Prediction

Represents expected future performance.

Contains

Predicted Views

Predicted Engagement

Predicted Growth

Confidence

Prediction Timestamp

Predictions are evaluated later.

---

## Learning Record

Represents

Prediction

↓

Reality

↓

Difference

↓

Learning

Learning records should never be deleted.

---

# Relationship Model

Every entity is connected.

```
Organization

↓

Channel

↓

Posts

↓

Deals

↓

Products

↓

Merchants

↓

Categories

↓

Competitors

↓

Analytics

↓

Insights

↓

Recommendations

↓

Learning
```

The platform should navigate relationships instead of repeatedly querying raw data.

---

# Ownership

Every entity has exactly one owner.

Example

Posts

Owner

Telegram

Merchant

Owner

Merchant Discovery

Analytics

Owner

Telegram

Prediction

Owner

Forecasting Engine

Recommendation

Owner

Reasoning Engine

No entity should have multiple sources of truth.

---

# Update Flow

Every update follows the same lifecycle.

```
External Source

↓

Collection

↓

Normalization

↓

Knowledge Layer

↓

Events

↓

Intelligence Engines

↓

Reasoning

↓

Dashboard
```

The Knowledge Layer always receives data before any intelligence engine processes it.

---

# Versioning

Every entity should maintain history.

Changes should never overwrite previous information.

Track

Created At

Updated At

Previous Version

Current Version

Source

Normalization Version

Collection Timestamp

---

# Query Rules

All downstream modules must query the Knowledge Layer.

No downstream engine may:

Call Telegram directly.

Call merchant websites directly.

Recalculate historical data independently.

Duplicate entities.

---

# Retention

Minimum retention

12 months.

Preferred retention

Unlimited.

Historical information should remain available for:

Trend analysis

Learning

Forecasting

Reporting

Benchmarking

---

# Security

Sensitive information should inherit organization-level permissions.

Users should only access:

Organizations they belong to.

Channels they manage.

Reports they are authorized to view.

Knowledge belonging to other organizations must remain isolated.

---

# Success Criteria

The Knowledge Layer is complete when:

- Every business entity has a single source of truth.
- Historical information is preserved.
- Relationships are maintained consistently.
- Intelligence engines consume structured knowledge instead of raw data.
- No duplicate entity ownership exists.
- Events propagate updates automatically.
- Future intelligence engines can be added without redesigning existing data structures.

---

# Out of Scope

The Knowledge Layer does not:

- Generate recommendations.
- Create strategies.
- Predict outcomes.
- Rank competitors.
- Score deals.

Its responsibility is to maintain reliable, reusable business knowledge that powers every intelligence engine.