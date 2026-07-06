# Post Classification Engine

Version: 1.0

Status: Engineering Specification

---

# Purpose

The Post Classification Engine is responsible for understanding every Telegram message.

The platform should never assume that every Telegram message is a single deal.

Instead, every message should first be classified into a post type.

This classification becomes the foundation for analytics, intelligence, planning and content generation.

---

# Core Principle

The platform analyzes POSTS.

Deals are only one type of content.

Every Telegram message belongs to one and only one Post Type.

---

# Responsibilities

The engine should

- Scan every Telegram message.
- Learn posting formats.
- Classify messages.
- Detect new post types.
- Learn posting templates.
- Learn writing style.
- Learn formatting style.
- Learn media usage.
- Feed downstream intelligence engines.

The engine must NOT

- Generate captions.
- Calculate metrics.
- Scrape merchant websites.

---

# Inputs

Telegram Channel History

Telegram Message

Media

Links

Images

Videos

Documents

Historical Performance

Knowledge Layer

---

# Classification Pipeline

Telegram Message

↓

Extract Structure

↓

Extract Components

↓

Identify Pattern

↓

Match Known Template

↓

Generate Confidence

↓

Assign Post Type

↓

Store Classification

---

# Post Types

The system must support dynamic post types.

The initial supported types are

## 1. Single Deal

Characteristics

- One product
- One affiliate link
- One merchant
- One CTA
- Usually one image

Example

Rain Coat ₹179

↓

Buy Now

↓

Affiliate Link

---

## 2. Deal Collection

Characteristics

- Multiple products
- Multiple affiliate links
- Shared theme
- Shared CTA

Example

Smartwatch Loot Under ₹1000

↓

Boat

↓

Noise

↓

Fire-Boltt

↓

Hammer

↓

Shop Now

---

## 3. Merchant Collection

Characteristics

Amazon Deals

Flipkart Deals

Ajio Deals

Nykaa Deals

Multiple products

Single merchant

---

## 4. Brand Collection

Examples

Boat Collection

Nike Collection

Samsung Collection

Apple Collection

---

## 5. Category Collection

Examples

Smartwatch Deals

Laptop Deals

Shoes Deals

Kitchen Deals

Beauty Deals

Travel Deals

---

## 6. Price Bucket Collection

Examples

Under ₹99

Under ₹199

Under ₹499

Under ₹999

Under ₹1999

The platform should learn new price buckets automatically.

---

## 7. Coupon Collection

Multiple coupon codes

Multiple merchants

One post

---

## 8. Bank Offer

Credit Card Offer

Debit Card Offer

EMI Offer

Instant Discount

---

## 9. Cashback Offer

Multiple cashback opportunities.

---

## 10. Giveaway

Contest

Referral

Lucky Draw

---

## 11. Festival Campaign

Prime Day

Big Billion Days

Diwali

Black Friday

New Year

Independence Day

The platform should automatically recognize recurring campaigns.

---

## 12. Announcement

Channel updates

Maintenance

Policy changes

New features

---

## 13. Engagement Post

Question

Poll

Survey

Quiz

Community interaction

---

# Component Extraction

For every post extract

Post Title

Products

Merchants

Brands

Categories

Deal Types

Affiliate Links

Short URLs

Images

Videos

Documents

Hashtags

CTA

Emoji Usage

Formatting

---

# Template Learning

The engine should continuously learn

Title structure

Price formatting

Discount formatting

Emoji placement

CTA placement

Line spacing

Affiliate link placement

Image placement

Media sequence

The platform should never rely on hardcoded templates.

---

# Pattern Learning

Examples

Most Loot posts

↓

Title

↓

Multiple Links

↓

Shop Now CTA

↓

Channel Mention

Single Deals

↓

Product Image

↓

Price

↓

CTA

↓

Affiliate Link

Patterns should be continuously updated.

---

# New Template Detection

When a previously unseen structure appears

↓

Generate Candidate Template

↓

Calculate Similarity

↓

Confidence

↓

Manual Review (optional)

↓

Knowledge Layer

The system should evolve over time.

---

# Confidence

Every classification must include

Classification

Confidence

Supporting Features

Detected Components

Reason

---

# User Interface

## Post Explorer

Filters

Post Type

Merchant

Category

Date

Performance

Template

---

## Template Library

Display

Detected Templates

Usage Count

Average Performance

Last Used

Trend

---

## Classification Detail

Display

Detected Components

Template Match

Confidence

Historical Similarity

Performance

---

# Events Consumed

TelegramMessageCollected

MessageNormalized

MediaExtracted

---

# Events Produced

PostClassified

TemplateDetected

NewTemplateDetected

PostComponentsExtracted

---

# Acceptance Criteria

The engine is complete when

- Every Telegram message is classified.
- New post types can be learned.
- Posting templates evolve automatically.
- Classification confidence is stored.
- Downstream engines consume classifications instead of raw messages.

---

# Out of Scope

The Post Classification Engine does not

- Generate Telegram posts.
- Publish content.
- Calculate business metrics.

Its responsibility is to understand the structure and type of every Telegram message.