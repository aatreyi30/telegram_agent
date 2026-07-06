# Campaign & Planning Engine

Version: 1.0

Status: Engineering Specification

---

# Purpose

The Campaign & Planning Engine transforms approved decisions into structured execution plans.

It creates daily, weekly and event-based campaign plans that maximize channel growth, audience engagement and business goals.

The engine answers questions such as:

- What should I post today?
- What should I post tomorrow?
- Which merchants should be prioritized this week?
- Which campaigns should be prepared?
- How should posting frequency change?
- What should be automated?

This engine creates plans.

It does not generate content.

---

# Responsibilities

The engine should

- Build posting plans.
- Build campaign plans.
- Build weekly calendars.
- Allocate merchants.
- Allocate deal types.
- Allocate posting windows.
- Recommend campaign priorities.
- Recommend automation schedules.

The engine must NOT

- Generate Telegram captions.
- Scrape Telegram.
- Calculate metrics.
- Publish posts.

---

# Inputs

Decision Engine

Reasoning Engine

Merchant Intelligence

Deal Intelligence

Competitor Intelligence

Audience Intelligence

Knowledge Layer

Organization Settings

Campaign History

Automation Rules

---

# Planning Pipeline

Every planning cycle follows

```
Business Goals

↓

Approved Decisions

↓

Available Deals

↓

Audience Behaviour

↓

Campaign Constraints

↓

Plan Generation

↓

Conflict Detection

↓

Optimization

↓

Campaign Plan
```

---

# Planning Levels

## Daily Plan

Generate a plan for today.

Examples

Number of posts

Recommended merchants

Recommended categories

Recommended deal types

Recommended posting windows

Priority deals

Expected engagement

Confidence

---

## Weekly Plan

Generate a seven-day plan.

Include

Daily themes

Merchant distribution

Category distribution

Posting frequency

Campaign preparation

Automation schedule

Expected growth

---

## Monthly Plan

Generate

Seasonal campaigns

Merchant rotation

Category planning

Growth objectives

Major sale events

Competitor monitoring priorities

---

## Event Plan

Support campaigns such as

Prime Day

Big Billion Days

Diwali

Black Friday

Republic Day

New Year

Independence Day

Organization-defined campaigns

The engine should automatically recognize upcoming events.

---

# Campaign Types

Examples

Merchant Campaign

Category Campaign

Festival Campaign

Flash Sale Campaign

Loot Deal Campaign

Brand Campaign

Awareness Campaign

Subscriber Growth Campaign

Engagement Campaign

Retention Campaign

Campaign types should remain configurable.

---

# Content Allocation

Every plan should recommend

Merchant

↓

Category

↓

Deal Type

↓

Posting Time

↓

Priority

↓

Expected Outcome

Example

Amazon

↓

Electronics

↓

Loot Deal

↓

12:30 PM

↓

High Priority

↓

Expected higher engagement

---

# Merchant Planning

Recommend

Which merchants should be increased.

Which merchants should be reduced.

Which merchants should be introduced.

Merchant diversity targets.

Merchant balance.

---

# Category Planning

Recommend

Growing categories.

Declining categories.

Seasonal categories.

Emerging categories.

Categories competitors are ignoring.

Categories competitors are dominating.

---

# Deal Planning

Recommend

Loot Deals

Coupons

Cashback

Flash Sales

Bank Offers

Bundles

Exchange Offers

The plan should balance deal diversity.

---

# Posting Schedule

Generate recommended posting windows.

Example

10:00 AM

↓

12:30 PM

↓

4:00 PM

↓

7:00 PM

↓

9:30 PM

Recommendations should use historical audience behaviour.

Never hardcode time slots.

---

# Posting Frequency

Recommend

Posts per day

Posts per week

Merchant frequency

Category frequency

Campaign frequency

Automation frequency

Recommendations should adapt to audience behaviour.

---

# Campaign Calendar

Generate

Upcoming campaigns

Current campaigns

Completed campaigns

Suggested campaigns

Campaign preparation checklist

Campaign performance

---

# Opportunity Planning

The engine should schedule opportunities.

Examples

Lowest historical price

Prime Day

Festival trend

Merchant promotion

Competitor gap

High-value loot deal

Limited availability

Urgent opportunities should be prioritized.

---

# Risk Planning

Detect

Campaign conflicts

Merchant overuse

Category imbalance

Posting overload

Audience fatigue

Low inventory

Weak deal quality

The engine should adjust plans automatically.

---

# Plan Optimization

Every generated plan should be optimized for

Business goals

Audience activity

Historical performance

Competitor behaviour

Merchant diversity

Category diversity

Deal quality

Posting consistency

Automation readiness

---

# Plan Review

Plans should support

Approve

Reject

Edit

Regenerate

Lock

Duplicate

Export

Organizations remain in control.

---

# Expected Outcome

Every plan should estimate

Expected reach

Expected engagement

Expected subscriber growth

Expected merchant diversity

Expected campaign success

Every prediction should include confidence.

---

# User Interface

## Planning Dashboard

Display

Today's Plan

Tomorrow's Plan

This Week

Upcoming Campaigns

Priority Opportunities

Automation Status

---

## Calendar View

Show

Daily schedule

Weekly calendar

Monthly calendar

Campaign timeline

---

## Campaign Detail

Display

Objectives

Merchants

Categories

Deals

Schedule

Expected Outcome

Confidence

Approval Status

---

## Opportunity Planner

Rank

Urgent opportunities

Recommended campaigns

Missed opportunities

Upcoming events

---

# Events Consumed

DecisionGenerated

DecisionApproved

OpportunityDetected

AudienceInsightGenerated

CompetitorInsightGenerated

MerchantInsightGenerated

DealInsightGenerated

CampaignCreated

---

# Events Produced

PlanGenerated

CampaignGenerated

PostingScheduleGenerated

AutomationPlanGenerated

PlanApproved

PlanUpdated

---

# Acceptance Criteria

The Campaign & Planning Engine is complete when

- Daily plans are generated automatically.
- Weekly plans are generated automatically.
- Campaign calendars are maintained.
- Merchant allocation is evidence-based.
- Posting schedules adapt to audience behaviour.
- Risks are detected before execution.
- Plans can be approved, edited or automated.
- Every recommendation references supporting decisions.

---

# Out of Scope

The Campaign & Planning Engine does not

- Generate Telegram captions.
- Publish Telegram posts.
- Calculate metrics.
- Collect external data.

Its responsibility is to convert approved business decisions into structured execution plans that can be reviewed manually or passed to the Content and Automation Engines.