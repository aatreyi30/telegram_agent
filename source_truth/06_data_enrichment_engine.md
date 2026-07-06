# Deal Enrichment Engine

Version: 1.0

Status: Core Data Intelligence Layer

---

# 🧠 Purpose

The Deal Enrichment Engine is responsible for transforming **raw scraped deals** into **validated, structured, and intelligence-rich deal objects**.

It sits between:

> Scraped Deal Data → Intelligence Layer → Classification + Growth Engine

---

# 🚨 Core Problem It Solves

Raw scraped deals (from GrabCash API or similar sources):

- contain inconsistent pricing
- lack merchant validation
- have incomplete metadata
- may include outdated or fake discounts
- are not structured for AI reasoning

This engine converts them into **trusted system-grade data**.

---

# 📊 Position in System Architecture

```
Scraping Layer (GrabCash API)
        ↓
Deal Enrichment Engine  ← YOU ARE HERE
        ↓
Post Classification Engine
        ↓
Channel Learning Engine
        ↓
Growth Engine
        ↓
Post Generation Engine
```

---

# ⚙️ INPUT

Raw Deal Object:

```json
{
  "title": "",
  "url": "",
  "merchant_url": "",
  "image": "",
  "scraped_price": "",
  "scraped_mrp": "",
  "discount": "",
  "timestamp": ""
}
```

---

# ⚙️ OUTPUT

Enriched Deal Object:

```json
{
  "deal_id": "",
  "title": "",
  "merchant": "",
  "merchant_type": "amazon | flipkart | myntra | unknown",
  "category": "",
  "original_price": "",
  "current_price": "",
  "discount_percent": "",
  "is_loot_deal": true/false,
  "deal_validity": "valid | invalid | unknown",
  "price_confidence_score": 0-1,
  "affiliate_link": "",
  "clean_url": "",
  "tags": [],
  "enrichment_source": ["amazon_api", "flipkart_api", "heuristics"],
  "last_verified_at": ""
}
```

---

# 🔍 CORE FUNCTIONS

---

## 1. Merchant Identification

Detect merchant from URL patterns:

- amazon.in → Amazon
- flipkart.com → Flipkart
- myntra.com → Myntra
- ajio.com → AJIO
- unknown → fallback scraping or classification

---

## 2. Product Validation Layer

Validate:

- Is price real?
- Is discount inflated?
- Is product active?
- Is deal expired?

Output:

- valid / invalid / unknown

---

## 3. Merchant API Enrichment

If merchant API exists:

Fetch:

- real price
- MRP
- discount %
- product metadata
- availability status

Fallback:

- scraping
- heuristic estimation

---

## 4. Deal Type Detection

Classify:

- Loot Deal (high discount, limited time)
- Normal Deal
- Coupon Deal
- Collection Deal

Rules derived from:

- discount %
- merchant type
- historical patterns

---

## 5. URL Normalization

Standardize:

- affiliate links
- tracking parameters
- shorteners
- deep links

---

## 6. Confidence Scoring

Each deal gets:

- price accuracy score
- merchant confidence
- enrichment completeness score

Formula (conceptual):

```
confidence =
  price_validity +
  merchant_match +
  api_verification +
  historical_pattern_match
```

---

# 🧠 ENRICHMENT SOURCES

System may use:

- Merchant APIs (Amazon, Flipkart, etc.)
- Internal scraping engine
- Historical deal database
- Competitor patterns (optional fallback)

---

# 🚫 STRICT RULES

- NEVER modify scraped raw data directly
- NEVER assume missing price data
- NEVER fabricate merchant information
- ALWAYS mark unknown values explicitly
- ALWAYS preserve raw input for traceability

---

# 🔁 SYSTEM BEHAVIOR

Every deal must pass through:

```
Raw Deal
  ↓
Merchant Detection
  ↓
API Enrichment
  ↓
Validation
  ↓
Classification
  ↓
Scoring
  ↓
Output
```

---

# 📈 WHY THIS ENGINE IS CRITICAL

Without this layer:

- fake discounts appear
- wrong merchants are assigned
- classification becomes unreliable
- Growth Engine produces bad strategies

With this layer:

- AI gets clean truth data
- Growth Engine becomes accurate
- post generation becomes reliable
- analytics becomes meaningful

---

# 🚀 SUCCESS CRITERIA

The engine is successful when:

- ≥90% merchant detection accuracy
- ≥85% price validation accuracy
- consistent deal classification
- reliable enrichment for top merchants
- no hallucinated deal data

---

# 🔥 FINAL NOTE

This engine is the **TRUTH LAYER of the entire system**.

Everything else depends on it.