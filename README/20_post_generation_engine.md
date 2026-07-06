# Post Generation Engine (With Integrated Ranking System)

Version: 2.0

Status: Execution Layer (Final Decision System)

---

# 🧠 PURPOSE

The Post Generation Engine is the **final decision-making layer** of the system.

It is responsible for:

> Selecting the BEST deals AND converting them into optimized Telegram posts.

This engine is NOT just formatting.

It is:

> 🧠 Ranking + Selection + Optimization + Publishing Brain

---

# 🚨 POSITION IN ARCHITECTURE

```
Ingestion Layer
   ↓
Enrichment Engine
   ↓
Classification Engine
   ↓
Growth Engine
   ↓
Reasoning Engine
   ↓
POST GENERATION ENGINE (YOU ARE HERE)
```

---

# ⚙️ INPUT

The engine receives:

```json
[
  {
    "deal_id": "",
    "title": "",
    "merchant": "",
    "category": "",
    "price_data": {},
    "discount_percent": "",
    "urgency_signals": [],
    "engagement_features": {},
    "historical_performance": {},
    "confidence_score": 0-1
  }
]
```

---

# 🚀 CORE RESPONSIBILITY

The engine performs 4 major steps:

---

# 1. 🧠 DEAL RANKING SYSTEM (CORE INTELLIGENCE)

Each deal is assigned a **Final Score**.

---

## 🔥 Ranking Formula (Conceptual)

```
Final Score =
  w1 × Engagement Probability
+ w2 × True Value Score
+ w3 × Urgency Score
+ w4 × Merchant Trust Score
+ w5 × Novelty Score
+ w6 × Historical Similar Performance
+ w7 × Confidence Score
```

---

## 📊 Feature Definitions

### 1. Engagement Probability
Predicted likelihood user will click/view based on:

- title structure
- emoji usage
- format style
- past performance patterns

---

### 2. True Value Score
Real value of deal:

- corrected discount %
- price inflation detection
- actual savings

---

### 3. Urgency Score
Derived from:

- “limited time”
- lightning deals
- stock scarcity signals

---

### 4. Merchant Trust Score
Learned dynamically from:

- historical conversions
- user engagement per merchant

---

### 5. Novelty Score
Penalizes:

- repeated deals
- repeated merchants
- repeated categories

---

### 6. Historical Performance Score
Matches deal with past similar high-performing deals.

---

# 2. 🎯 DEAL SELECTION SYSTEM

After ranking:

## Selection Rules:

- Top N deals selected (configurable)
- Must ensure diversity:

### Required mix:
- 1 Loot Deal (high urgency)
- 1 Trending Deal
- 1 Budget Deal
- 1 High-value deal
- 1 Exploration deal (new pattern)

---

# 3. ✍️ POST OPTIMIZATION SYSTEM

Each selected deal is transformed into:

## Telegram-Optimized Format:

### Includes:
- Hook headline
- Emoji hierarchy
- Price highlight
- Affiliate link
- CTA section

---

## Example Output Style:

```
🔥 Smartwatch Loot Under ₹999 😍

boAt Smartwatch – ₹799 (🔥 60% OFF)
Noise Smartwatch – ₹899
Fire-Boltt Smartwatch – ₹949

👉 Grab Now: [Affiliate Link]
🔁 Share with friends
```

---

# 4. 📤 PUBLISHING SYSTEM

Final step:

- Formats message for Telegram
- Injects affiliate links
- Applies tracking URLs
- Sends to channel(s)

---

# 🧠 INTERNAL MODULES

The engine is internally divided into:

```
Post Generation Engine
   ├── Ranking Module
   ├── Selection Module
   ├── Formatting Module
   ├── Publishing Module
```

---

# 🚫 STRICT RULES

- NEVER hardcode ranking rules
- NEVER assume merchant performance
- NEVER guess engagement without data
- NEVER generate posts without ranking step
- ALWAYS use enriched data only

---

# 📊 DATA DEPENDENCIES

This engine depends on:

- Deal Enrichment Engine
- Post Classification Engine
- Channel Learning Engine
- Competitor Intelligence Engine

---

# 🧠 WHY THIS ENGINE IS CRITICAL

This is the **final intelligence layer before user sees anything.**

It ensures:

- best deals are surfaced first
- irrelevant deals are filtered out
- engagement is maximized
- system learns continuously

---

# 🚀 SUCCESS CRITERIA

System is successful when:

- top-ranked deals get highest engagement
- CTR improves over time
- users trust channel content
- low-value deals are automatically filtered out
- ranking improves without manual tuning

---

# 🔥 FINAL STATEMENT

This engine is NOT a formatter.

It is the:

> 🧠 “Decision Brain of the Entire System”