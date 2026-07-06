# Discovery Engine

Version: 1.0

Status: Engineering Specification

---

# Purpose

The Discovery Engine continuously identifies new business entities that should be added to the platform.

Unlike the Data Collection Engine, which collects information from known sources, the Discovery Engine finds previously unknown entities.

Examples include:

- Business competitors
- Telegram channels
- Merchants
- Brands
- Products
- Categories
- Deal types
- Offer formats
- Content patterns

The Discovery Engine should continuously improve the platform's understanding without requiring manual configuration.

---

# Responsibilities

The Discovery Engine is responsible for:

- Discovering new competitors
- Finding official Telegram channels
- Discovering new merchants
- Discovering new brands
- Discovering new categories
- Discovering new products
- Discovering new deal patterns
- Discovering new content formats

The Discovery Engine is NOT responsible for:

- Data collection
- Metric calculation
- AI recommendations
- Strategy generation
- Dashboard updates

---

# Design Principles

Discovery should always be:

- Evidence based
- Repeatable
- Explainable
- Verifiable

Nothing should be added permanently without passing validation.

---

# Discovery Pipeline

Every discovery process follows the same lifecycle.

```
Candidate

↓

Validation

↓

Confidence Score

↓

Approval Rules

↓

Knowledge Layer

↓

Monitoring
```

---

# Discovery Types

The platform supports multiple discovery pipelines.

---

# 1. Business Competitor Discovery

## Purpose

Identify companies that compete with the organization.

Input

Organization

↓

Website

↓

Business Category

↓

Public Web

Processing

- Identify business category.
- Search for competing companies.
- Remove irrelevant businesses.
- Calculate relevance score.

Output

List of verified business competitors.

Example

GrabOn

↓

DesiDime

↓

CashKaro

↓

Zoutons

↓

CouponzGuru

These are business competitors.

Not Telegram competitors.

---

# Validation Rules

A competitor should have:

- Same business domain.
- Similar customer segment.
- Similar products or services.
- Active business presence.

Businesses failing validation should not be monitored.

---

# 2. Telegram Channel Discovery

Purpose

Find Telegram channels belonging to discovered competitors.

Input

Business Competitor

↓

Official Website

↓

Public Search

↓

Social Profiles

↓

Telegram

Validation

Possible validation signals:

- Telegram linked from official website
- Telegram linked from verified social media
- Matching branding
- Matching business identity
- Matching contact information

Output

Verified Telegram channels.

The system should avoid monitoring unofficial channels.

---

# 3. Merchant Discovery

Purpose

Discover merchants appearing in Telegram posts.

Sources

Owned channels

Competitor channels

Merchant websites

Processing

- Detect merchant mentions.
- Standardize names.
- Match existing merchants.
- Create new merchant only if no verified match exists.

Examples

Amazon

Flipkart

Myntra

Ajio

Nykaa

Boat

Merchant lists should never be hardcoded.

---

# 4. Brand Discovery

Purpose

Identify product brands.

Examples

Apple

Samsung

Boat

Sony

Nike

Processing

Extract

↓

Validate

↓

Standardize

↓

Store

---

# 5. Product Discovery

Purpose

Identify products mentioned in posts.

Example

Boat Airdopes 141

↓

Brand

Boat

↓

Category

Audio

↓

Merchant

Amazon

↓

Deal

The same product should not be duplicated.

---

# 6. Category Discovery

Purpose

Automatically learn new business categories.

Examples

Existing

Electronics

Fashion

New

Travel

OTT

Insurance

Gift Cards

Finance

The platform should evolve without code changes.

---

# 7. Deal Type Discovery

Purpose

Learn new promotional formats.

Examples

Loot Deal

Flash Sale

Coupon

Bank Offer

Cashback

Buy One Get One

Exchange Offer

No predefined list should limit future discovery.

---

# 8. Content Pattern Discovery

Purpose

Identify recurring posting patterns.

Examples

Morning posting

Weekend campaigns

Festival campaigns

Urgency messaging

Limited-time offers

Countdown offers

Video-first campaigns

Image-first campaigns

CTA variations

These patterns support future reasoning.

---

# Discovery Confidence

Every discovered entity should include:

- Confidence Score
- Discovery Source
- Discovery Time
- Validation Status
- Supporting Evidence

Entities below the confidence threshold should be flagged for review instead of automatically becoming part of the active knowledge base.

---

# Manual Review

Users should be able to:

- Approve discovered entities.
- Reject discovered entities.
- Merge duplicates.
- Rename entities.
- Ignore future suggestions.

Manual decisions should improve future discovery.

---

# Re-discovery

Discovery is continuous.

Examples

A new competitor enters the market.

A competitor launches a new Telegram channel.

A merchant changes branding.

A new category becomes popular.

The engine should periodically re-run discovery to detect changes.

---

# Events Consumed

- OrganizationCreated
- ChannelConnected
- PostNormalized
- MerchantDetected
- ProductDetected
- ManualRefreshRequested

---

# Events Produced

- CompetitorDiscovered
- TelegramChannelDiscovered
- MerchantDiscovered
- BrandDiscovered
- ProductDiscovered
- CategoryDiscovered
- DealTypeDiscovered
- ContentPatternDiscovered

---

# Failure Handling

If discovery cannot be completed:

- Keep previously verified entities.
- Retry automatically where appropriate.
- Log the reason for failure.
- Avoid deleting verified knowledge.

---

# Acceptance Criteria

The Discovery Engine is complete when:

- Business competitors are identified without hardcoded lists.
- Official Telegram channels are discovered and validated.
- New merchants, brands, products, and categories are learned automatically.
- Discovery decisions include confidence and evidence.
- Duplicate entities are minimized.
- Discovery improves over time through user feedback.

---

# Out of Scope

The Discovery Engine does not:

- Monitor competitor performance.
- Calculate metrics.
- Generate recommendations.
- Produce AI-generated insights.

Its only responsibility is to discover and validate new entities that become part of the platform's knowledge.