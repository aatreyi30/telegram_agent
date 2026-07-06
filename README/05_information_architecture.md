# Information Architecture

Version: 1.0

Status: Foundation Document

---

# Purpose

This document defines the logical structure of the Telegram Growth & Retention Intelligence Platform.

It specifies:

- Core business entities
- Relationships between entities
- Ownership of data
- Source of truth
- Information flow
- Capability boundaries

This document does NOT describe database tables.

Database implementation is covered separately.

This document defines the business model.

---

# Design Philosophy

The platform is NOT page-centric.

The platform is NOT AI-centric.

The platform is INFORMATION-centric.

Every feature should consume information from a shared knowledge layer instead of maintaining its own isolated data.

---

# Core Architecture

```

Organization

↓

Channels

↓

Posts

↓

Structured Knowledge

↓

Intelligence Engines

↓

Reasoning Engine

↓

Automation

↓

Learning

```

Everything derives from the channel.

Nothing bypasses the knowledge layer.

---

# Level 1 Entity

## Organization

Purpose

Represents a business or team.

Responsibilities

Owns users.

Owns channels.

Owns automation rules.

Owns reports.

Owns historical knowledge.

Owns organization-wide intelligence.

Relationships

```

Organization

├── Users

├── Channels

├── Reports

├── Alerts

├── Knowledge

└── Automation

```

Source of Truth

Internal Database

---

# Level 2 Entity

## Channel

Purpose

Represents one Telegram channel.

Every intelligence engine ultimately operates around channels.

Channel contains

Metadata

Posts

Audience

Analytics

Competitors

Strategies

Content

Learning History

Automation

Relationships

```

Organization

↓

Channel

├── Posts

├── Audience

├── Competitors

├── Merchants

├── Deals

├── Analytics

├── Reports

└── Automation

```

---

# Level 3 Entity

## Post

A post is the smallest business object.

It is NOT raw Telegram text.

It is structured knowledge.

Every post should contain

Message

Media

Merchant

Products

Prices

Coupons

Offers

Categories

Topics

Links

Publishing Time

Views

Engagement

Performance

Every intelligence engine uses Posts.

---

# Derived Entity

## Deal

Not every post is a deal.

A deal is extracted from one or more posts.

Deal contains

Merchant

Product

MRP

Current Price

Coupon

Offer

Discount

Availability

Historical Price

Deal Score

Status

Relationships

```

Post

↓

Deal

↓

Merchant

↓

Product

```

---

# Derived Entity

## Merchant

Represents a brand, marketplace or seller.

Examples

Amazon

Flipkart

Myntra

Ajio

Nykaa

Boat

etc.

The platform should never rely on hardcoded merchants.

Merchant Profile

Merchant Name

Merchant Type

Categories

Historical Performance

Average Discounts

Average Engagement

Competitor Usage

Organization Usage

Trend

Recommendation Score

---

# Derived Entity

## Product

Represents an individual product.

Examples

Boat Airdopes

iPhone

Samsung TV

Nike Shoes

Every Product contains

Merchant

Category

Brand

MRP

Historical Prices

Current Prices

Deals

Performance

Mentions

Relationships

```

Merchant

↓

Products

↓

Deals

↓

Posts

```

---

# Derived Entity

## Category

Categories are NOT predefined.

Categories should be discovered.

Examples

Electronics

Travel

Finance

Beauty

Groceries

Fashion

Gaming

Software

Insurance

OTT

Categories contain

Subcategories

Products

Merchants

Posts

Performance

Growth

Competitor Usage

---

# Intelligence Entity

## Competitor

Represents another Telegram channel.

Competitor contains

Metadata

Historical Posts

Posting Behaviour

Merchant Distribution

Category Distribution

Posting Frequency

Media Behaviour

Growth Trends

Offer Types

Pattern Detection

Similarity Score

Reasoning

Competitors are continuously updated.

---

# Intelligence Entity

## Audience

Represents channel audience behaviour.

Audience contains

Growth

Retention

Activity

Viewing Behaviour

Engagement

Returning Users

Leaving Users

Behavioural Segments

Audience should never be treated as a single number.

---

# Intelligence Entity

## Analytics

Analytics represent measured observations.

Analytics are facts.

Examples

Views

Subscribers

Reactions

Forwards

Posting Frequency

CTR

Reach

Analytics should never contain recommendations.

Recommendations belong to Reasoning.

---

# Intelligence Entity

## Insights

Insights are interpretations of analytics.

Example

Analytics

Views decreased 12%.

Insight

Views decreased because fashion posts underperformed electronics during the last week.

Insights require reasoning.

---

# Intelligence Entity

## Recommendation

Recommendations are actions.

Recommendations always contain

Action

Reason

Evidence

Confidence

Supporting Data

Historical Context

Expected Outcome

No recommendation should exist independently.

Every recommendation should be traceable.

---

# Intelligence Entity

## Prediction

Represents expected future outcomes.

Prediction contains

Expected Views

Expected Engagement

Expected Subscriber Growth

Confidence

Supporting Factors

Predictions become learning data.

---

# Intelligence Entity

## Learning Record

Represents the comparison between

Prediction

and

Reality.

Contains

Prediction

Actual

Difference

Learning

Model Update

Learning Records should never be deleted.

---

# Knowledge Layer

Every entity ultimately becomes knowledge.

```

Posts

Deals

Products

Merchants

Audience

Competitors

Analytics

Predictions

Learning

↓

Knowledge Layer

↓

Reasoning

```

No reasoning engine should directly consume raw Telegram messages.

---

# Capability Mapping

Every capability owns specific entities.

Channel Intelligence

Owns

Posts

Analytics

Audience

Competitor Intelligence

Owns

Competitors

Patterns

Similarity

Merchant Intelligence

Owns

Merchants

Performance

Trends

Deal Intelligence

Owns

Deals

Products

Discounts

Audience Intelligence

Owns

Behaviour

Activity

Retention

Learning Engine

Owns

Predictions

Results

Improvements

Reasoning Engine

Consumes everything.

Produces

Insights

Recommendations

Strategies

Automation Engine

Consumes

Recommendations

Schedules

Approval Rules

Publishing

---

# Source of Truth

Every entity should have exactly one owner.

Example

Posts

Source

Telegram

Merchant

Source

Merchant Discovery Engine

Analytics

Source

Telegram Analytics

Recommendation

Source

Reasoning Engine

Prediction

Source

Forecasting Engine

Learning

Source

Learning Engine

No duplicate ownership should exist.

---

# Information Flow

```

Telegram

↓

Collection

↓

Normalization

↓

Knowledge Layer

↓

Intelligence Engines

↓

Reasoning

↓

Dashboard

↓

Automation

↓

Learning

↓

Knowledge Layer

```

The system forms a continuous feedback loop.

---

# UI Mapping

Pages do not own information.

Pages visualize information.

Dashboard

Shows

Everything important.

Competitor Page

Shows

Competitor Intelligence.

Merchant Page

Shows

Merchant Intelligence.

Automation

Shows

Automation State.

Reports

Show

Historical Intelligence.

Pages should never calculate business logic.

---

# Guiding Principles

Information should exist once.

Knowledge should be reusable.

Recommendations should always reference knowledge.

Learning should improve future recommendations.

UI should never become the source of truth.

AI should consume knowledge rather than raw messages.

---

# Success Criteria

Every future feature should answer the following questions before implementation:

Which entities does it use?

Who owns those entities?

What is the source of truth?

Which intelligence engine updates them?

Which pages consume them?

If these questions cannot be answered, the feature is not sufficiently defined for implementation.