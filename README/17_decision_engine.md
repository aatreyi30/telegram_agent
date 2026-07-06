# Decision Engine

Version: 1.0

Status: Engineering Specification

---

# Purpose

The Decision Engine converts intelligence into executable business decisions.

The Reasoning Engine explains:

- What happened
- Why it happened

The Decision Engine determines:

- What should be done now
- What should be done next
- What should not be done

Every recommendation produced by the platform must pass through the Decision Engine before becoming part of a strategy or automation workflow.

---

# Responsibilities

The Decision Engine should:

- Prioritize opportunities.
- Rank recommendations.
- Resolve conflicts.
- Consider business constraints.
- Decide the next best action.
- Generate decision records.
- Provide confidence and supporting evidence.

The Decision Engine must NOT:

- Collect data.
- Calculate metrics.
- Generate Telegram captions.
- Publish posts.

---

# Core Principle

A recommendation is not a decision.

The Decision Engine converts multiple recommendations into one coherent action plan.

---

# Inputs

The Decision Engine consumes outputs from:

Reasoning Engine

Merchant Intelligence

Deal Intelligence

Competitor Intelligence

Audience Intelligence

Knowledge Layer

Automation Settings

Organization Settings

Business Goals

Historical Learning Records

---

# Decision Pipeline

Every decision follows the same process.

```
Business Goal

↓

Available Opportunities

↓

Business Constraints

↓

Priority Scoring

↓

Conflict Resolution

↓

Decision

↓

Expected Outcome

↓

Store Decision Record
```

---

# Business Goals

Examples

Increase Subscribers

Increase Views

Increase Engagement

Increase Merchant Diversity

Promote Specific Merchants

Maximize Loot Deals

Increase Daily Posting

Improve Posting Quality

Reduce Manual Work

Business goals are configurable per organization.

---

# Available Opportunities

Examples

Trending merchant

Lowest historical price

Competitor gap

Audience active

Festival campaign

Seasonal category

Emerging deal type

High-quality loot deal

New merchant

Every opportunity should include evidence and confidence.

---

# Business Constraints

The Decision Engine must consider constraints.

Examples

Posting limits

Approval requirements

Merchant restrictions

Campaign schedules

Manual overrides

Automation rules

Content availability

Time windows

Organization preferences

No decision should ignore active constraints.

---

# Priority Scoring

Each candidate action receives a priority score.

Possible factors

Expected Impact

Confidence

Urgency

Historical Success

Business Goal Alignment

Competition

Audience Relevance

Seasonality

Priority scoring should be configurable.

---

# Conflict Resolution

Conflicts are common.

Example

Recommendation A

Post Amazon Electronics

Recommendation B

Post Flipkart Fashion

Recommendation C

Avoid posting due to low audience activity

The engine should evaluate:

Business goals

Historical performance

Audience behaviour

Current campaigns

Expected outcome

A single prioritized decision should be produced.

Alternative decisions should remain visible.

---

# Decision Types

Examples

Post Immediately

Schedule Later

Wait

Ignore

Review Manually

Increase Frequency

Reduce Frequency

Change Merchant Mix

Change Category Mix

Change Posting Time

Adjust Content Style

Launch Campaign

Pause Campaign

---

# Decision Record

Every decision should contain:

Decision ID

Timestamp

Business Goal

Selected Action

Alternative Actions

Evidence

Reasoning Summary

Confidence

Priority Score

Expected Outcome

Review Status

Execution Status

---

# Expected Outcome

Every decision should predict an expected outcome.

Examples

Higher engagement

Higher reach

Better merchant diversity

Improved posting consistency

Increased subscriber growth

Expected outcomes should be measurable.

---

# Learning Loop

Every executed decision should be evaluated.

Decision

↓

Execution

↓

Actual Result

↓

Difference

↓

Learning Record

↓

Future Decision Improvement

Poor decisions should improve future decision-making.

---

# Decision Categories

## Content Decisions

What content should be published?

## Merchant Decisions

Which merchants should be prioritized?

## Deal Decisions

Which deals deserve immediate attention?

## Timing Decisions

When should content be published?

## Strategy Decisions

Should posting behaviour change?

## Automation Decisions

Can this decision be executed automatically?

---

# Decision Confidence

Confidence should depend on:

Supporting evidence

Historical consistency

Agreement across intelligence engines

Data freshness

Confidence should never be estimated without evidence.

---

# User Interface

## Decision Center

Display

Recommended Actions

Priority

Confidence

Expected Outcome

Status

---

## Decision Detail

Display

Business Goal

Evidence

Reasoning Summary

Alternative Options

Expected Impact

Execution Status

Learning History

---

## Decision Timeline

Chronological history of all generated decisions.

Include

Decision

Execution

Outcome

Learning

---

# Events Consumed

RecommendationGenerated

OpportunityDetected

AudienceInsightGenerated

CompetitorInsightGenerated

MerchantInsightGenerated

DealInsightGenerated

AutomationStatusUpdated

---

# Events Produced

DecisionGenerated

DecisionApproved

DecisionRejected

DecisionExecuted

DecisionLearningRecorded

---

# Acceptance Criteria

The Decision Engine is complete when:

- Multiple recommendations are combined into coherent decisions.
- Decisions respect business goals and constraints.
- Every decision includes supporting evidence.
- Alternative actions are preserved.
- Expected outcomes are defined.
- Decision quality improves through learning.
- Decisions are ready for Strategy or Automation.

---

# Out of Scope

The Decision Engine does not:

- Generate Telegram content.
- Publish posts.
- Collect external data.
- Calculate raw metrics.

Its responsibility is to determine the best action based on verified intelligence and organizational goals.