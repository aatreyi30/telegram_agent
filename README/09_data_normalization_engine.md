# Data Normalization Engine

Version: 1.0

Status: Engineering Specification

---

# Purpose

The Data Normalization Engine converts raw collected data into structured business entities.

This engine is responsible for transforming Telegram messages, merchant data, and external content into a consistent internal format that can be understood by downstream intelligence engines.

No AI reasoning occurs during normalization.

Normalization identifies facts.

Reasoning happens later.

---

# Objectives

The normalization engine should:

- Convert unstructured content into structured entities.
- Standardize data across all sources.
- Remove ambiguity where possible.
- Preserve unknown values without guessing.
- Produce reusable business objects.

---

# Guiding Principles

Normalization is deterministic.

Given the same input, the output should always be identical.

The engine must never:

- Guess missing prices.
- Guess merchants.
- Invent categories.
- Modify historical data.
- Create recommendations.

---

# Input Sources

The engine receives data only from the Data Collection Engine.

Possible inputs include:

- Telegram posts
- Telegram metadata
- Merchant product pages
- Competitor posts
- Images
- Videos
- URLs

---

# Output

The engine produces structured entities.

Examples:

Post

Deal

Merchant

Product

Brand

Category

Coupon

Offer

Price

Media

Link

Hashtag

Language

Each entity should have its own identifier.

---

# Normalization Pipeline

Every record follows the same pipeline.

```
Raw Data

↓

Validation

↓

Parsing

↓

Entity Extraction

↓

Relationship Mapping

↓

Standardization

↓

Storage

↓

Event Emission
```

---

# Step 1 — Validation

Purpose

Ensure the incoming data is usable.

Examples

- Required fields present
- Valid timestamps
- Valid message identifiers
- Valid URLs
- Supported media

Invalid records should be rejected with detailed error logs.

---

# Step 2 — Parsing

Convert raw messages into machine-readable components.

Example

Input

"🔥 Boat Airdopes 141
MRP ₹1999
Now ₹699
Use Coupon SAVE100"

Parsed Fields

Message Text

Numbers

Currency

Coupon

URLs

Mentions

Hashtags

Emoji

Media References

No business meaning should be assigned during parsing.

---

# Step 3 — Entity Extraction

Purpose

Identify business entities.

Possible entities include:

Merchant

Product

Brand

Category

Subcategory

Price

Discount

Coupon

Bank Offer

Offer Type

Affiliate Link

Product URL

The extraction process should return:

Value

Confidence

Source

Location within the message

Unknown values remain Unknown.

---

# Step 4 — Relationship Mapping

Entities rarely exist independently.

Relationships must be created.

Example

```
Merchant

↓

Product

↓

Deal

↓

Telegram Post

↓

Channel
```

Another example

```
Category

↓

Merchant

↓

Competitor

↓

Performance
```

Relationships should be stored separately from the original message.

---

# Step 5 — Standardization

Purpose

Ensure consistent formatting.

Examples

Prices

₹699

699 INR

Rs.699

↓

699

Merchant Names

Amazon India

amazon

AMAZON

↓

Amazon

Categories

Mobiles

Mobile Phones

Smartphones

↓

Mobile Phones

Only formatting is standardized.

Meaning should not change.

---

# Step 6 — Storage

Store both:

Raw Record

Structured Record

Never discard raw data.

Structured data should reference the raw source.

---

# Step 7 — Event Emission

After successful normalization, publish events.

Examples

PostNormalized

DealExtracted

MerchantDetected

PriceUpdated

CategoryDetected

ProductDetected

These events trigger downstream intelligence engines.

---

# Business Entities

The engine should produce the following entities.

---

## Channel

Contains

Channel ID

Name

Username

Description

Language

Metadata

---

## Post

Contains

Post ID

Channel

Timestamp

Text

Media

Views

Reactions

Links

Language

Status

---

## Merchant

Contains

Merchant Name

Merchant Type

Website

Marketplace Flag

Confidence

---

## Product

Contains

Product Name

Brand

Merchant

Category

Subcategory

Product URL

---

## Deal

Contains

Original Price

Current Price

Discount

Coupon

Offer Type

Bank Offer

Effective Price

Availability

---

## Category

Contains

Category

Subcategory

Parent Category

Confidence

Categories should remain dynamic.

---

## Media

Contains

Type

Resolution

Dimensions

Duration

Thumbnail

OCR Status

---

## Link

Contains

Destination

Domain

Affiliate Status

Tracking Parameters

---

# Unknown Data

If information cannot be extracted:

Store

Unknown

Do not:

Guess

Infer

Invent

Substitute

Unknown values may be enriched later.

---

# Versioning

Normalization rules will evolve.

Every normalized record should include:

Normalization Version

Timestamp

Source Version

This allows future reprocessing without losing history.

---

# Error Handling

Possible failures

Unsupported format

Corrupted media

Malformed URL

Unreadable message

Unknown encoding

Handling

Reject only the affected entity.

Preserve the original raw record.

Log detailed diagnostics.

Continue processing remaining entities.

---

# Acceptance Criteria

The engine is complete when:

- Raw Telegram posts become structured entities.
- Merchant names are standardized.
- Prices are normalized.
- Products and deals are linked.
- Unknown values are preserved.
- Raw records remain available.
- Every normalized entity references its original source.
- Downstream engines receive normalization events automatically.

---

# Out of Scope

This engine does not:

- Score deals.
- Rank merchants.
- Generate insights.
- Produce recommendations.
- Predict performance.
- Explain trends.

Its only responsibility is to transform raw information into reliable structured knowledge.