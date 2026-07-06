# Product Research Framework

Version: 1.0

Status: Research Specification

---

# Purpose

Before implementing the dashboard, AI engines or analytics, the team must conduct structured research.

The objective is to ensure every feature is based on verified platform capabilities, user needs and measurable business value.

No dashboard component should be designed based on assumptions.

---

# Research Principles

Every finding must include

- Source
- Date
- Evidence
- Confidence
- Limitations

If information cannot be verified, it must be marked as an Open Question.

Never assume API capabilities.

Never assume competitor behaviour.

Never assume user needs.

---

# Research Deliverables

The research phase should produce

- Verified platform capabilities
- Verified technical limitations
- Verified competitor analysis
- User requirements
- Dashboard opportunities
- AI opportunities
- Product differentiation opportunities
- Open questions
- Risks
- Implementation recommendations

---

# Research Track 1 — Telegram Platform

Goal

Understand exactly what Telegram provides and what must be built by our platform.

Research

- Telegram Bot API
- MTProto API
- Telegram Analytics
- Channel Admin APIs
- Export capabilities
- Historical limitations
- Rate limits

Questions

- Which analytics are available?
- Which analytics are API accessible?
- Which analytics require scraping?
- Which analytics are unavailable?
- What historical data is accessible?
- How frequently can data be refreshed?
- What permissions are required?

Deliverable

Available Data

Unavailable Data

Possible Workarounds

Implementation Recommendation

---

# Research Track 2 — Competitor Discovery

Goal

Identify the real business competitors and map their Telegram presence.

Start from businesses, not Telegram.

Example

GrabOn

↓

Competitors

↓

Telegram Channels

Research

- DesiDime
- CouponzGuru
- Zoutons
- CashKaro
- Freekaamaal
- Other verified competitors

Questions

- Official Telegram channel
- Subscriber count
- Posting frequency
- Posting schedule
- Categories
- Merchants
- Campaigns
- Media usage
- CTA style
- URL patterns
- Affiliate patterns
- Posting consistency

Deliverable

Top competitor database.

---

# Research Track 3 — Telegram Content Research

Collect historical Telegram posts.

Target

2,000–5,000 posts.

Objectives

Identify

- Post Types
- Templates
- Writing styles
- CTA patterns
- Emoji usage
- Media usage
- Link placement
- Collection structures

Deliverable

Master Post Type Library.

---

# Research Track 4 — Merchant Research

Research

Amazon

Flipkart

Myntra

AJIO

Nykaa

Boat

Croma

Reliance Digital

FirstCry

Other merchants

Questions

- Affiliate support
- Sale calendar
- Campaigns
- Product URLs
- Coupon structure
- APIs
- Public data availability

Deliverable

Merchant Knowledge Base.

---

# Research Track 5 — Dashboard Research

Research

Telegram Analytics

YouTube Studio

Meta Business Suite

Google Analytics 4

HubSpot

Mixpanel

Amplitude

Semrush

Ahrefs

For every metric ask

Does it help users make a decision?

If the answer is No

Do not copy it.

Deliverable

Dashboard Opportunity Matrix.

---

# Research Track 6 — User Research

Interview Telegram channel admins.

Questions

What do you check first every morning?

What consumes most of your time?

How do you discover competitors?

How do you decide posting time?

How do you evaluate successful posts?

What reports do you prepare?

What information do you wish Telegram provided?

Deliverable

User Pain Point Report.

---

# Research Track 7 — AI Opportunity Research

Identify repetitive decisions.

Examples

Merchant selection

Posting schedule

Loot generation

Competitor monitoring

Campaign planning

Daily summary

Executive report

Opportunity detection

Content generation

Deliverable

AI Opportunity Backlog.

---

# Research Track 8 — Historical Learning

Research

How should learning records be stored?

Should reasoning be stored?

Should summaries be stored?

How long should history be retained?

How should previous learnings influence future recommendations?

Deliverable

Historical Learning Strategy.

---

# Research Track 9 — Automation

Research

Scheduling

Publishing

Retry policies

Approvals

Notifications

Multi-channel management

Failure recovery

Deliverable

Automation Requirements.

---

# Research Track 10 — Product Differentiation

Question

Why would someone pay for this platform instead of using Telegram Analytics?

List every capability Telegram does NOT provide.

Examples

Competitor Intelligence

AI Daily Briefing

Reasoning

Campaign Planning

Historical Learning

Automatic Summaries

Merchant Intelligence

Opportunity Detection

Deal Intelligence

Deliverable

Unique Value Proposition Document.

---

# Research Track 11 — Deal Psychology & Conversion

Research

Why do some posts receive more engagement?

Questions

- Do price bucket collections outperform single deals?
- What title structures perform best?
- Does product ordering influence clicks?
- Which CTA performs best?
- How many products should a loot collection contain?
- Does emoji usage influence engagement?
- Do images outperform text-only posts?
- Which post formats generate the highest sharing?

Deliverable

Content Optimization Guidelines.

---

# Research Completion Criteria

Research is complete when

- Every finding has supporting evidence.
- Every assumption is validated or rejected.
- Unknowns are documented.
- Dashboard requirements are evidence-based.
- AI opportunities are prioritized.
- Technical constraints are understood.
- Product differentiation is clearly defined.

Only after completing this document should dashboard design begin.