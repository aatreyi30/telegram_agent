# Competitor Intelligence Engine

Version: 1.0

Status: Engineering Specification

---

# Purpose

The Competitor Intelligence Engine continuously analyzes competitor behaviour to understand strategy, identify changes, detect opportunities and generate evidence-backed recommendations.

Unlike traditional analytics, this engine focuses on understanding competitor decisions rather than simply reporting statistics.

The objective is to answer:

- What changed?
- Why did it change?
- How are competitors executing their strategy?
- What should we learn?
- What should we do differently?

---

# Responsibilities

The engine should

- Monitor competitors continuously.
- Detect strategic changes.
- Explain behaviour changes.
- Compare competitors.
- Benchmark our channel.
- Detect opportunities.
- Detect threats.
- Generate strategic recommendations.

The engine must NOT

- Scrape Telegram directly.
- Calculate metrics.
- Generate captions.
- Publish content.

---

# Inputs

Knowledge Layer

- Competitors
- Competitor Channels
- Posts
- Deals
- Merchants
- Products
- Categories

Metrics Engine

- Competitor Metrics
- Merchant Metrics
- Deal Metrics
- Category Metrics
- Channel Metrics

Merchant Intelligence

Deal Intelligence

Discovery Engine

---

# Core Principle

Never report a number without answering

WHY?

Every observation must include supporting evidence.

---

# Intelligence Pipeline

```
Competitor Data

↓

Pattern Detection

↓

Behaviour Change Detection

↓

Evidence Collection

↓

Reasoning

↓

Confidence

↓

Recommendation
```

---

# Business Questions

The engine should answer

## Strategy

What strategy is this competitor following?

Has their strategy changed?

What categories are they investing in?

Which merchants are they prioritizing?

---

## Posting Behaviour

How often do they post?

Has posting frequency changed?

Which days?

Which hours?

Are they posting immediately after deals appear?

---

## Merchant Behaviour

Which merchants dominate?

Which merchants disappeared?

Which merchants are growing?

Which merchants are seasonal?

---

## Deal Behaviour

What type of deals do they prefer?

Loot deals?

Coupons?

Cashback?

Flash sales?

Bundle offers?

---

## Category Behaviour

Which categories are growing?

Which categories are declining?

Are they entering new categories?

---

## Content Behaviour

Average caption length

CTA style

Emoji usage

Urgency words

Media usage

Carousel usage

Images

Videos

GIFs

Link placement

Coupon placement

Hashtag usage

Content structure

---

## Timing Behaviour

Posting hours

Posting gaps

Weekend behaviour

Festival behaviour

Campaign behaviour

Prime Day

Big Billion Days

Black Friday

Diwali

End of Month

Salary Week

---

# Strategy Detection

The engine should detect changes such as

Electronics increased

↓

Merchant changed

↓

Average discount increased

↓

Posting frequency doubled

↓

Competitor targeting Prime Day

This is strategy.

Not statistics.

---

# Pattern Detection

The engine should learn patterns such as

Morning posts perform better.

Fashion only posted on weekends.

Electronics increase during sales.

Amazon dominates during Prime events.

Flipkart dominates during BBD.

Festival campaigns begin 5 days early.

These become reusable knowledge.

---

# Opportunity Detection

Examples

Competitors ignoring Beauty.

Competitors reducing Travel.

Competitors stopped using Myntra.

Competitors increased Amazon.

Competitors not posting Gift Cards.

Merchant becoming available.

New category emerging.

Every opportunity must include evidence.

---

# Threat Detection

Examples

Competitor posting twice as often.

Competitor entered our strongest category.

Competitor launched new Telegram channel.

Merchant partnership expanded.

Average discount improving.

Content quality improving.

Threats should be ranked.

---

# Benchmarking

Compare

Our channel

↓

Top 10 competitors

Across

Posting

Merchants

Deals

Categories

Timing

Growth

Content

Consistency

No benchmark should rely on a single metric.

---

# Daily Intelligence Report

Every day generate

Yesterday

What happened?

↓

Why?

↓

Evidence

↓

Impact

↓

Recommendation

Example

Yesterday

Competitors increased Amazon electronics posting by 41%.

Reason

Prime Day campaign preparation.

Evidence

- Merchant increase
- Discount increase
- Posting increase

Recommendation

Increase Amazon loot coverage over the next 48 hours.

Confidence

High

---

# Weekly Intelligence Report

Summarize

Biggest winners

Biggest losers

Fastest growing merchants

Fastest growing categories

New deal types

New competitors

Content changes

Posting changes

Strategic shifts

Missed opportunities

Recommended actions

---

# Competitor Profile

Every competitor should have

Business Summary

Telegram Channels

Merchant Mix

Category Mix

Deal Mix

Posting Behaviour

Content Style

Historical Timeline

Growth

Threat Score

Opportunity Score

Similarity Score

Learning Timeline

---

# Reasoning Framework

Every conclusion follows

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

No recommendation without evidence.

---

# User Interface

## Competitor Dashboard

Overview

Top Competitors

Threats

Opportunities

Latest Changes

Strategic Alerts

---

## Competitor Timeline

Day-by-day

What changed

Why

Evidence

---

## Competitor Comparison

Compare

Any competitors

Against

Our channel

---

## Strategy Explorer

View

Merchant strategy

Category strategy

Deal strategy

Timing strategy

Content strategy

Campaign strategy

---

## Daily Intelligence Feed

Instead of charts

Display

Yesterday

↓

Observed

↓

Reasoned

↓

Recommended

---

# Events Consumed

MerchantUpdated

DealUpdated

CompetitorUpdated

MetricsUpdated

DiscoveryCompleted

---

# Events Produced

CompetitorStrategyUpdated

CompetitorThreatDetected

CompetitorOpportunityDetected

CompetitorInsightGenerated

CompetitorRecommendationGenerated

---

# Acceptance Criteria

The engine is complete when

- Competitors are continuously analyzed.
- Strategy changes are detected automatically.
- Every insight includes evidence.
- Every recommendation includes reasoning.
- Threats are ranked.
- Opportunities are ranked.
- Historical behaviour is preserved.
- Benchmarking compares behaviour instead of isolated metrics.

---

# Out of Scope

The Competitor Intelligence Engine does not

- Scrape Telegram.
- Calculate raw metrics.
- Generate Telegram posts.
- Execute automation.

Its purpose is to transform competitor behaviour into strategic business intelligence.