# Data Validation Matrix
## Feature Buildability Assessment — Telegram Deal Channel AI Platform

**Methodology:** Every data requirement was evaluated against what was directly confirmed in prior research. No data source is assumed to exist unless it was verified by: live redirect resolution, robots.txt inspection, API documentation review, or confirmed public access. Where data is unverifiable from research, it is marked LOW confidence or BLOCKED.

**Confidence scale:**
- **HIGH** — Data source confirmed, access method verified, known structure
- **MEDIUM** — Data source exists, access partially confirmed, some uncertainty in schema or rate limits
- **LOW** — Data source exists but access is problematic, unclear, or requires unverified steps
- **BLOCKED** — Data cannot be collected; feature cannot be built as described

---

## SECTION 1: CONFIRMED DATA SOURCES INVENTORY

This is what actually exists and is accessible, based on research. Everything in the matrix below derives from this table.

| Source | What It Provides | Access Method | Confirmed? | Notes |
|---|---|---|---|---|
| **Telegram Bot API** | Own channel: message content, timestamps, view counts, forward counts, reactions, subscriber count | REST API with bot token | YES | Bot must be added to channel as admin. Views = total cumulative (not time-series without polling). |
| **Telegram MTProto API** | Full channel history, more detailed stats than Bot API | Requires phone number auth (Telethon/Pyrogram) | YES (documented) | Higher complexity; operator must authorize |
| **Telegram t.me/s/ web preview** | Competitor public channel: recent posts, visible view counts, forward counts, post content | HTTP scrape (no auth) | YES — confirmed in this project's own methodology | Depth limited (typically 20–50 most recent posts per paginated request); view counts visible in HTML |
| **Amazon Creators API** (replaced PA-API May 15, 2026) | Product data: title, ASIN, price, availability, images, category | REST API with affiliate credentials | YES — documented at affiliate-program.amazon.com/creatorsapi/docs | Replaces PA-API; schema partially documented; requires active Associates account with qualifying sales |
| **Flipkart Affiliate API** | Product catalog, pricing, availability | REST API with affiliate credentials | YES (documented) | Rate limits unconfirmed; robots.txt blocks direct scraping but API is separate |
| **AJIO HasOffers/TUNE API** | Affiliate click tracking, campaign stats | REST API at tracking.ajio.business | YES — confirmed from redirect chain resolution (pid, sub1, sub2 params visible) | Direct affiliate program; no product search API. Click tracking only, not product catalog. |
| **boAt Shopify JSON endpoint** | Product price and availability | HTTP GET /products/[handle].json | YES — Shopify stores expose this by default | boAt has no protection; Shopify JSON is public |
| **Reliance Digital** | Product pages | HTTP scrape | MEDIUM — confirmed low protection in robots.txt | No sitemap-level block; JS rendering may be partial |
| **Amazon commission rates** | Commission % by category | Public documentation page | YES — verified June 2026 rates | Rates change; requires periodic re-verification |
| **Flipkart commission rates** | Commission % by category | Public affiliate homepage | YES — verified from homepage | Less granular than Amazon's documentation |
| **Sale calendar (major events)** | Amazon GIF, Flipkart BBD, Myntra EORS, AJIO GOAT, Diwali sale dates | Public announcements, merchant websites | YES (public knowledge) | Announced months in advance; flash sales are NOT predictable |
| **Own channel post history** | Historical posts with timestamps, view counts | Telegram Bot API or MTProto API | YES | Full history available; must poll for time-series view data |
| **Own affiliate link shortener** (if using grbn.in, fkrt.cc etc.) | Click counts per link | Affiliate portal dashboard (not API) | PARTIAL — portal exists; API access unconfirmed | Click data exists in portal; no confirmed API for programmatic access |

---

**Data sources that do NOT exist or are BLOCKED:**

| Source | Status | Reason |
|---|---|---|
| AJIO product catalog / pricing | BLOCKED | Akamai CDN returns Access Denied (confirmed in research); no public product API |
| Nykaa product catalog / pricing | BLOCKED | Akamai CDN; affiliate network identity unknown; no confirmed API |
| Croma product catalog / pricing | BLOCKED | Akamai CDN protection confirmed |
| Zepto product catalog / pricing | BLOCKED | robots.txt: Disallow: / — total block; no affiliate program |
| Blinkit product catalog / pricing | BLOCKED | Cloudflare block confirmed (Ray ID observed); no affiliate program |
| Tata CLiQ | BLOCKED (AI-specific) | Explicitly blocks ClaudeBot, GeminiBot, ChatGPT-User, PerplexityBot by name in robots.txt |
| Myntra product API | UNKNOWN | Redirect chain resolves (myntr.it → linkredirect.in → myntra.com); no confirmed product data API |
| AJIO commission rates | BLOCKED | Not published publicly; direct affiliate program with undisclosed rates |
| Nykaa commission rates | BLOCKED | Affiliate network unidentified; rates not documented anywhere in research |
| Telegram click-through rate | DOES NOT EXIST | Telegram does not provide CTR. Views ≠ clicks. No native link click tracking. |
| Affiliate conversion / revenue per post | NOT AVAILABLE without integration | Exists only inside affiliate portal dashboards; no standard API across all merchants |
| Competitor channel click-through data | DOES NOT EXIST | t.me/s/ shows views/forwards only; link click data is private to the channel operator |
| Historical price data (90-day average) | DOES NOT EXIST on day 1 | No external API for AJIO/Nykaa/Myntra price history; Amazon price history = CamelCamelCamel (no public API); must be self-accumulated |
| Time-series view velocity (views at T+1h, T+4h) | DOES NOT EXIST unless polled | Telegram API provides current view count only; must snapshot at multiple intervals to reconstruct velocity curve |

---

## SECTION 2: FEATURE DATA VALIDATION MATRIX

---

### FEATURE 1 — POST COPY GENERATION

| Field | Detail |
|---|---|
| **Required Data** | (A) Post templates by type. (B) Product name, price, merchant, category. (C) Historical engagement data per template variant to optimize (optional for v1) |
| **Data Source** | (A) Templates: extracted from GrabOn channel reverse engineering — already in research documents. (B) Product data: merchant APIs or operator input. (C) Own channel Telegram Bot API |
| **Collection Method** | (A) Hardcoded from research (18 post types documented, 3 full GrabOn templates verbatim). (B) API call at post-creation time. (C) Continuous polling of own channel stats |
| **API or Scraping** | (A) None — static. (B) Amazon Creators API / Flipkart Affiliate API / manual operator input for non-API merchants. (C) Telegram Bot API |
| **Refresh Frequency** | Templates: static until manually updated. Product data: per-post (on demand). Optimization data: daily batch |
| **Historical Availability** | Templates: immediately available (already extracted). Historical engagement data: available from day 1 via Telegram Bot API if channel has prior post history |
| **Confidence** | **HIGH** |
| **Known Limitations** | Template optimization (which variant performs best) requires minimum 60 posts per template variant to be statistically reliable — cold start problem. Merchants without API (AJIO, Nykaa, Croma) require operator to manually input product details. |
| **Fallback Strategy** | V1: static templates, operator fills product fields manually. V2: merchant API auto-fills. V3: performance-based variant selection. Feature is buildable without any API — operator provides product details, platform generates copy. |
| **Status** | ✅ BUILDABLE |

---

### FEATURE 2 — AFFILIATE LINK GENERATION

| Field | Detail |
|---|---|
| **Required Data** | (A) Product identifier (ASIN for Amazon, product ID for Flipkart, product URL for others). (B) Operator's affiliate credentials per merchant. (C) Merchant-specific affiliate parameter structure |
| **Data Source** | (A) From product URL or operator input. (B) Operator must supply — cannot be shared at platform level. (C) Confirmed from redirect chain research: Amazon tag format, Flipkart affid/affExtParam2, AJIO pid/sub1/sub2, Myntra redirect chain |
| **Collection Method** | (A) URL parsing or API lookup. (B) One-time setup by operator (stored securely). (C) Hardcoded from research — parameter structures are stable |
| **API or Scraping** | Amazon: Creators API (link generation endpoint). Flipkart: Affiliate API (deep link generator). AJIO: tracking.ajio.business (HasOffers link generation — requires affiliate account). Myntra/Nykaa: URL construction only (no confirmed API). boAt: no affiliate program — cannot generate tracked links. |
| **Refresh Frequency** | Credentials: static (until operator updates). Parameter structures: stable (verify quarterly). Generated links: per post |
| **Historical Availability** | Not applicable — link generation is per-request |
| **Confidence** | **HIGH** for Amazon and Flipkart. **MEDIUM** for AJIO (API structure inferred from redirect params; full HasOffers API docs not reviewed). **LOW** for Myntra and Nykaa (affiliate network identity unconfirmed). **NOT POSSIBLE** for boAt, Zepto, Blinkit (no affiliate programs) |
| **Known Limitations** | Every operator needs their own affiliate account per merchant — platform cannot use a shared affiliate ID (violation of affiliate ToS for most programs). boAt has no affiliate program; Zepto and Blinkit have no affiliate programs. These merchants cannot generate tracked affiliate links — any links to them are untracked. Amazon Creators API qualification requires active associates account with recent qualifying sales. |
| **Fallback Strategy** | For merchants without confirmed API: construct affiliate URL from known parameter template + operator-supplied credentials. For merchants with no affiliate program (boAt, Zepto, Blinkit): generate untracked direct link; flag to operator that revenue tracking is unavailable. |
| **Status** | ✅ BUILDABLE (Amazon, Flipkart) / ⚠️ PARTIAL (AJIO, Myntra) / 🚫 UNTRACKED (boAt, Zepto, Blinkit) |

---

### FEATURE 3 — MERCHANT SELECTION

| Field | Detail |
|---|---|
| **Required Data** | (A) Current commission rates by merchant and category. (B) Active sale status per merchant. (C) Own channel historical CTR or engagement rate per merchant |
| **Data Source** | (A) Amazon: public documentation (verified June 2026). Flipkart: public affiliate homepage (verified). AJIO: NOT PUBLIC — rate undisclosed. Nykaa: NOT PUBLIC. Others: unknown. (B) Sale calendar (public announcements). (C) Own post history from Telegram Bot API + post classification by merchant |
| **Collection Method** | (A) Periodic scrape of affiliate commission documentation pages (Amazon/Flipkart). AJIO/Nykaa: requires login to affiliate portal — cannot be automated without credentials and portal scraping. (B) Manual curation of sale calendar + periodic scraping of merchant "Sale" landing pages. (C) NLP classification of historical posts by merchant mentioned |
| **API or Scraping** | (A) Amazon/Flipkart: HTTP scrape of public commission tables (no API; these are human-readable documentation pages). AJIO/Nykaa: portal login scrape or manual input only. (B) HTTP scrape of merchant homepages for sale banner detection. (C) Telegram Bot API |
| **Refresh Frequency** | Commission rates: monthly (rates change infrequently; major changes happen quarterly). Sale status: daily. Per-merchant engagement: weekly batch |
| **Historical Availability** | Amazon/Flipkart commission rates: immediately available from documentation. AJIO/Nykaa commission rates: NOT AVAILABLE without affiliate portal credentials. Historical per-merchant engagement: available from day 1 if channel history exists. |
| **Confidence** | **HIGH** for Amazon and Flipkart commission data. **BLOCKED** for AJIO and Nykaa commission rates. **HIGH** for sale calendar (major events). **LOW** for flash sale detection (unpredictable). **MEDIUM** for per-merchant engagement (depends on post classification quality) |
| **Known Limitations** | AJIO and Nykaa commission rates are private — operators who use these merchants cannot get an automated commission rate comparison. The "merchant selection" recommendation will be incomplete for channels that heavily use AJIO or Nykaa. Per-merchant CTR (clicks ÷ views) is unavailable — Telegram does not expose click data. Engagement proxy (views, forwards) is a weak substitute for actual CTR. |
| **Fallback Strategy** | Show commission rates for Amazon and Flipkart only (confirmed). For AJIO/Nykaa: require operator to manually input their commission rate once (stored, used in ranking). For sale status: daily scrape of merchant homepage for sale banners. |
| **Status** | ⚠️ PARTIAL — Buildable for Amazon/Flipkart; AJIO/Nykaa commission rates require operator manual input |

---

### FEATURE 4 — PRODUCT / DEAL SELECTION

| Field | Detail |
|---|---|
| **Required Data** | (A) Product feed with current prices and discount status. (B) Price history (90-day average to verify genuine discount). (C) Stock availability. (D) Category classification |
| **Data Source** | (A+C+D) Amazon: Creators API. Flipkart: Affiliate API. AJIO: NONE (Akamai blocks). Nykaa: NONE (Akamai blocks). Croma: NONE (Akamai blocks). boAt: Shopify JSON endpoint. Reliance Digital: HTTP scrape (medium difficulty). Zepto/Blinkit: BLOCKED. (B) Price history: must be self-accumulated — no external API exists for AJIO/Nykaa/Myntra price history; CamelCamelCamel covers Amazon (unofficial, no API) |
| **Collection Method** | Amazon/Flipkart: API polling (deal feeds, category browse). boAt: scheduled Shopify JSON fetch. Reliance Digital: periodic HTTP scrape. AJIO/Nykaa/Croma: CANNOT fetch. Price history: must run own price tracker — store prices fetched at each collection cycle to build history over time |
| **API or Scraping** | Amazon: Creators API. Flipkart: Affiliate API. boAt: Shopify JSON. Reliance Digital: scraping (low risk). AJIO/Nykaa/Croma/Zepto/Blinkit: BLOCKED |
| **Refresh Frequency** | Real-time / hourly for flash deals (Amazon Lightning Deals expire in 2–4 hours). Daily for standard products. Price history: snapshot every 6 hours to build 90-day average |
| **Historical Availability** | Price history: ZERO on day 1. Must run for 90 days before "90-day average discount" metric is meaningful. Amazon and Flipkart product feeds: immediately available via API. AJIO/Nykaa: never available programmatically. |
| **Confidence** | **HIGH** for Amazon and Flipkart (API confirmed). **LOW** for AJIO, Nykaa, Croma, Myntra (no programmatic access). **BLOCKED** for Zepto and Blinkit. **MEDIUM** for price history (90-day average requires 90 days of accumulation) |
| **Known Limitations** | The most-used merchants in Indian deal channels after Amazon/Flipkart are AJIO and Myntra (fashion-heavy). Both are inaccessible programmatically. This limits automated deal discovery to Amazon and Flipkart only — approximately 50–60% of the deal channel content universe. Price history cold start: genuine discount detection (current price vs. 90-day average) is unreliable for the first 90 days of operation. Amazon Creators API qualification barrier is a real risk — new channels with no qualifying sales cannot access product data via API. |
| **Fallback Strategy** | For AJIO/Nykaa: operator manually inputs deal details (product name, price, discount %). Platform handles copy generation and link creation but cannot auto-source or verify. For price history cold start: use price as a ratio vs. MRP (listed original price) as initial proxy until 90-day data accumulates. |
| **Status** | ⚠️ PARTIAL — Automated sourcing available for Amazon and Flipkart only. AJIO, Nykaa, Croma, Zepto, Blinkit require manual operator input |

---

### FEATURE 5 — COLLECTION CURATION

| Field | Detail |
|---|---|
| **Required Data** | Same as Feature 4 (product feed) + collection theme/price ceiling from operator |
| **Data Source** | Same as Feature 4 |
| **Collection Method** | Same as Feature 4 — filter product feed by category + price ceiling; rank by discount depth |
| **API or Scraping** | Same as Feature 4 |
| **Refresh Frequency** | Same as Feature 4 |
| **Historical Availability** | Same as Feature 4 |
| **Confidence** | **HIGH** for Amazon/Flipkart collections. **BLOCKED** for AJIO/Nykaa collections |
| **Known Limitations** | Cannot auto-curate AJIO or Nykaa fashion collections — the dominant format in GrabOn's "loot" posts. Fashion deal channels heavily feature AJIO/Myntra/Nykaa, all of which are inaccessible. Amazon/Flipkart collections are fully automatable. AJIO/Nykaa/Myntra collections require operator to provide product details. |
| **Fallback Strategy** | Semi-automated: operator searches AJIO/Nykaa manually, selects products, enters product names/prices into a structured form; platform handles formatting, affiliate links, and copy generation |
| **Status** | ⚠️ PARTIAL — Full automation for Amazon/Flipkart. Assisted (not automated) for fashion merchants |

---

### FEATURE 6 — POST TYPE SELECTION

| Field | Detail |
|---|---|
| **Required Data** | (A) Own channel historical posts classified by post type. (B) View counts per post. (C) Current context: time of day, recent post types, sale status |
| **Data Source** | (A+B) Telegram Bot API — full message history with view counts. (C) System clock + sale calendar |
| **Collection Method** | (A) Pull full channel history via Telegram Bot API; classify each post by type using NLP/pattern matching (18 post types are already documented with distinguishing features from reverse engineering). (B) Included in API response. (C) Runtime context |
| **API or Scraping** | Telegram Bot API (getHistory + getMessages). No external scraping needed |
| **Refresh Frequency** | Historical classification: one-time batch + incremental as new posts are added. Recommendations: real-time at post creation time |
| **Historical Availability** | Telegram Bot API provides full channel message history from channel creation. All historical posts accessible immediately. View counts are current totals (not time-series), but sufficient for relative comparison. |
| **Confidence** | **HIGH** — data fully available; classification accuracy depends on NLP implementation quality |
| **Known Limitations** | Post type classification using NLP will have errors for ambiguous posts (e.g., a post that is both a collection and a campaign burst). Minimum data requirement: 100+ posts to identify reliable patterns by post type. New channels or channels with fewer than 100 posts will have low-confidence recommendations. View counts are cumulative totals, not "views earned in first 24 hours" — older posts naturally have higher total counts, which must be age-normalized for fair comparison. |
| **Fallback Strategy** | V1: provide fixed schedule recommendations based on industry patterns (e.g., "Collection posts perform best on Friday evening — this is a pattern observed across competitor channels from t.me/s/ data"). V2: switch to personalized recommendations once 100+ posts accumulated |
| **Status** | ✅ BUILDABLE |

---

### FEATURE 7 — POSTING TIME SELECTION

| Field | Detail |
|---|---|
| **Required Data** | Own channel posts with publish timestamps + view counts at multiple time intervals (T+1h, T+4h, T+24h) to build view velocity curves by time of day |
| **Data Source** | Telegram Bot API (message timestamp + current view count) |
| **Collection Method** | Must run a polling job: fetch view count for each post at scheduled intervals (T+1h, T+4h, T+24h after publish). This builds a time-series of view accumulation that can be correlated with publish time. Cannot be reconstructed retroactively — historical posts only have current (total cumulative) views. |
| **API or Scraping** | Telegram Bot API — getMessages with specific message IDs; poll on schedule |
| **Refresh Frequency** | Poll each post at T+1h, T+4h, T+24h after publish. Analysis: weekly batch to update posting time recommendations |
| **Historical Availability** | **CRITICAL GAP**: Existing historical posts have only current total view counts — NOT view velocity at specific time windows. Time-series data does not exist retroactively. The polling infrastructure must run for 30+ days before meaningful T+4h velocity data exists for pattern analysis. |
| **Confidence** | **MEDIUM** — data will be available but requires 30+ days of polling before recommendations are data-backed |
| **Known Limitations** | View velocity data is not retroactively available. The platform cannot use existing historical posts to bootstrap this feature. Requires 30-day data collection period before recommendations are meaningful. During the first 30 days, posting time recommendations must be based on industry patterns (competitor channel data, general Telegram usage patterns) rather than own-channel data. Additionally, Telegram view counts continue to accumulate indefinitely — a post from 6 months ago still gets views from channel history browsers; this inflates total view counts for older posts relative to recent ones. |
| **Fallback Strategy** | V1: use competitor channel posting time patterns as baseline (CouponzGuru posts at :34 past every 2 hours; CouponDunia uses 2-hour intervals — these are observed patterns that can be used as defaults). V2: own channel velocity data once 30+ days of polling accumulates |
| **Status** | ✅ BUILDABLE — with 30-day data collection delay for personalized recommendations |

---

### FEATURE 8 — DEAL EXPIRY & POST DELETION

| Field | Detail |
|---|---|
| **Required Data** | (A) Affiliate links from recent posts (last 7 days). (B) Current price and stock status of linked products |
| **Data Source** | (A) Telegram Bot API — own channel message history with link extraction. (B) Amazon Creators API, Flipkart Affiliate API, boAt Shopify JSON, Reliance Digital HTTP scrape |
| **Collection Method** | (A) Parse messages from Bot API, extract URLs (amzn.to, fkrt.cc, grbn.in shortlinks). Resolve shortlinks to get final product URLs. (B) Query each merchant's product endpoint for price and stock status. |
| **API or Scraping** | Amazon: Creators API. Flipkart: Affiliate API. boAt: Shopify JSON. Reliance Digital: HTTP scrape. AJIO/Nykaa/Croma: CANNOT CHECK |
| **Refresh Frequency** | Every 2–4 hours for posts from the last 7 days. Daily for posts from the last 30 days |
| **Historical Availability** | Full post history with links available immediately from Telegram API. Product status data fetched in real-time — no historical component needed |
| **Confidence** | **HIGH** for Amazon and Flipkart. **MEDIUM** for boAt and Reliance Digital. **BLOCKED** for AJIO, Nykaa, Croma, Zepto, Blinkit |
| **Known Limitations** | Posts linking to AJIO, Nykaa, Croma, Zepto, or Blinkit products cannot be auto-monitored. Channel operators who post heavily from these merchants (particularly AJIO fashion deals, which are a primary GrabOn content type) will not receive expiry alerts for a significant portion of their posts. Shortlink resolution adds latency — each short URL (amzn.to, fkrt.cc) must be followed to get the final product URL before the product API can be queried. |
| **Fallback Strategy** | For unmonitorable merchants (AJIO, Nykaa, Croma): apply a time-based rule (flag posts older than 5 days for manual review, since AJIO sale deals typically run 3–7 days). No automatic deletion — always alert operator for final decision |
| **Status** | ⚠️ PARTIAL — Monitoring available for Amazon/Flipkart/boAt; not available for AJIO, Nykaa, Croma |

---

### FEATURE 9 — CAMPAIGN PLANNING

| Field | Detail |
|---|---|
| **Required Data** | (A) Sale event calendar (future dates for major sales). (B) Historical performance during past sale events (own channel). (C) Post templates for campaign burst formats |
| **Data Source** | (A) Public announcements from Amazon, Flipkart, Myntra, AJIO — manually curated + periodic scrape of merchant "upcoming sales" pages. (B) Telegram Bot API — own channel historical posts classified by sale event period. (C) Templates from research (Template C: Campaign Burst, already extracted) |
| **Collection Method** | (A) Manual curation baseline + scheduled scraping of merchant news/offer pages. (B) Date-range query on own channel history via Telegram API — pull all posts during known past sale periods; compute average engagement vs. non-sale periods. (C) Hardcoded from research |
| **API or Scraping** | (A) HTTP scrape of merchant websites (medium difficulty for most). (B) Telegram Bot API. (C) Static |
| **Refresh Frequency** | Sale calendar: weekly check for new announcements. Historical performance: computed once per past sale, stored |
| **Historical Availability** | (A) Sale calendar: available immediately for known annual events (GIF, BBD, EORS, Republic Day, Diwali — all known dates for 2026). Flash sales: unpredictable, cannot be calendared in advance. (B) Historical sale performance: available only if channel has operated through previous sale events. New channels have no baseline. |
| **Confidence** | **HIGH** for known annual sale calendar. **LOW** for flash sale detection. **MEDIUM** for historical performance (depends on channel age and whether prior sales occurred) |
| **Known Limitations** | Flash sales (Amazon Lightning Deals, Flipkart Super Deals) are not announced in advance — they cannot appear in a campaign calendar. New channels with no prior sale event history have no performance baseline for planning. Sale dates vary year to year (Amazon GIF is "October" but specific dates shift annually and are confirmed close to the event). |
| **Fallback Strategy** | Maintain a manually-curated sale calendar as the foundation; supplement with automated merchant homepage monitoring for "Sale starts in X days" banners. For new channels: use industry benchmarks from competitor channel data (channels tend to 3–5x posting frequency during GIF) as baseline recommendations |
| **Status** | ✅ BUILDABLE for major annual events. ⚠️ PARTIAL for flash sale detection |

---

### FEATURE 10 — COMPETITOR MONITORING

| Field | Detail |
|---|---|
| **Required Data** | (A) Recent posts from competitor channels. (B) View counts per post. (C) Forward counts per post. (D) Post content (merchant, post type, product category) |
| **Data Source** | Telegram t.me/s/ web preview — confirmed accessible without authentication. All target competitor channels (DesiDime, CouponzGuru, CashKaro, FreeKaaMaal, CouponDunia) are public channels |
| **Collection Method** | Periodic HTTP scrape of t.me/s/[channel_username] with pagination via ?before=[post_id] parameter. Parse HTML for post content, view count, forward count, timestamp. Classify posts by merchant and type using NLP |
| **API or Scraping** | Scraping only — no official Telegram API for third-party public channels. t.me/s/ confirmed as functional scraping target |
| **Refresh Frequency** | Hourly (to catch burst campaigns within 60 minutes of start) |
| **Historical Availability** | t.me/s/ pagination allows going back through channel history via ?before=[post_id]. In research, this successfully retrieved 119 posts from GrabOn's channel. Depth depends on channel size; most channels have months of history accessible. |
| **Confidence** | **MEDIUM** — scraping works today; Telegram could add bot detection or change t.me/s/ structure at any time without notice. No official API guarantee. |
| **Known Limitations** | (1) t.me/s/ view counts are visible but may be approximated (Telegram rounds large view counts). (2) No click-through data available for competitor channels — only views and forwards. (3) Telegram could change the t.me/s/ web preview format or add bot protection, breaking the scraper. (4) Post classification accuracy depends on NLP quality — same limitations as Feature 6. (5) Competitor channels not on the monitored list will not appear in alerts. (6) Forward counts are cumulative, not time-windowed — cannot tell if forwards happened in the first hour or the first week. |
| **Fallback Strategy** | If t.me/s/ becomes inaccessible: manual monitoring notification ("Please manually check @DesiDime for new posts — automated monitoring unavailable"). No technical fallback exists for public channel monitoring without Telegram API auth for third-party channels. |
| **Status** | ✅ BUILDABLE — with acknowledged scraping dependency risk |

---

### FEATURE 11 — DEAL PRICE VERIFICATION

| Field | Detail |
|---|---|
| **Required Data** | Current price of the product being posted, fetched at post-creation time |
| **Data Source** | Amazon: Creators API (GetItems endpoint). Flipkart: Affiliate API (product lookup). boAt: Shopify /products/[handle].json. Reliance Digital: HTTP GET product page (low protection). AJIO/Nykaa/Croma: BLOCKED |
| **Collection Method** | At post creation, extract product identifier from URL → query merchant API or endpoint → compare returned price to operator-stated price → flag mismatch |
| **API or Scraping** | Amazon: Creators API. Flipkart: Affiliate API. boAt: Shopify JSON (no auth needed). Reliance Digital: scrape. AJIO/Nykaa/Croma: cannot verify |
| **Refresh Frequency** | Per post (on demand, at posting time) |
| **Historical Availability** | Not applicable — verification is point-in-time |
| **Confidence** | **HIGH** for Amazon, Flipkart, boAt. **MEDIUM** for Reliance Digital. **BLOCKED** for AJIO, Nykaa, Croma, Zepto, Blinkit |
| **Known Limitations** | AJIO and Nykaa are among the highest-volume merchants for Indian deal channels — price verification is unavailable for both. This means the most common source of price errors (AJIO flash deals with rapidly changing prices) cannot be auto-verified. Amazon Creators API requires affiliate account qualification. |
| **Fallback Strategy** | For unverifiable merchants: display warning "⚠️ Price cannot be auto-verified for AJIO — confirm manually before posting." For Amazon/Flipkart: auto-verify with API call. |
| **Status** | ⚠️ PARTIAL — Verified for Amazon/Flipkart/boAt; manual flag for AJIO/Nykaa/Croma |

---

### FEATURE 12 — WEEKLY EXECUTIVE SUMMARY

| Field | Detail |
|---|---|
| **Required Data** | (A) Own channel: post count, total views, per-post views, forward counts, subscriber delta — for current week and prior week. (B) Competitor channels: same metrics at summary level. (C) Affiliate revenue — optional, high value |
| **Data Source** | (A) Telegram Bot API — own channel message history + view counts. (B) Telegram t.me/s/ scraping — competitor channels. (C) Affiliate portal export — NOT programmatically accessible for most platforms |
| **Collection Method** | (A) Weekly batch query of own channel via Bot API; compute week-over-week deltas. (B) Weekly summary scrape of top 5 competitor channels. (C) Manual export from affiliate portal, uploaded by operator — or not included if operator doesn't connect |
| **API or Scraping** | (A) Telegram Bot API. (B) t.me/s/ scrape. (C) No standard API; portal scrape or manual CSV upload |
| **Refresh Frequency** | Weekly (delivered Monday morning for previous week) |
| **Historical Availability** | Own channel: full history available from day 1. Competitor channel: t.me/s/ history available. Revenue data: available only if operator manually provides |
| **Confidence** | **HIGH** for engagement metrics (views, forwards, subscriber count). **MEDIUM** for competitive benchmarking (t.me/s/ limitations apply). **LOW** for revenue attribution (no standard API; manual only) |
| **Known Limitations** | Telegram does not report subscriber count changes via Bot API in real-time — must poll subscriber count at start and end of week to compute delta. Revenue data cannot be auto-fetched without operator manually connecting their affiliate dashboard. The summary will be engagement-complete but revenue-incomplete unless operator takes additional setup steps. |
| **Fallback Strategy** | Deliver full engagement summary without revenue. Add a manual revenue input field where operators can optionally enter their weekly affiliate earnings to include in the summary |
| **Status** | ✅ BUILDABLE for engagement metrics. ⚠️ PARTIAL for revenue attribution |

---

### FEATURE 13 — OPPORTUNITY DETECTION

This feature has six sub-components, each with independent data requirements.

| Sub-Feature | Required Data | Source | Confidence | Status |
|---|---|---|---|---|
| **Commission rate change** | Amazon/Flipkart commission rate changes | Periodic scrape of commission documentation pages | MEDIUM (pages exist; structure may change) | ⚠️ PARTIAL (Amazon/Flipkart only; AJIO/Nykaa: BLOCKED) |
| **Trending product in competitor channels** | Product/brand mentions across competitor channels in last 24h | t.me/s/ scrape + NLP extraction | MEDIUM | ⚠️ BUILDABLE with scraping dependency |
| **Competitor posting spike** | Hourly post count for monitored competitor channels | t.me/s/ hourly scrape | MEDIUM | ⚠️ BUILDABLE with scraping dependency |
| **Price drop alert** | Price history for specific products operator has posted | Own price tracking database (accumulated over time) | LOW on day 1 / MEDIUM after 90 days | ⚠️ DELAYED — cold start |
| **Sale announced** | New sale event announcements from merchant sites | HTTP scrape of merchant sale pages + merchant PR pages | MEDIUM | ⚠️ BUILDABLE |
| **Category gap** | Own channel post distribution by category + competitor distribution | Telegram Bot API (own) + t.me/s/ (competitors) + NLP classification | MEDIUM | ⚠️ BUILDABLE |

**Overall Confidence: MEDIUM**

**Known Limitations:** No single sub-feature delivers immediate out-of-box value. All require some combination of cold start period (price history), NLP classification (product/category detection), or scraping infrastructure (competitor monitoring). The commission rate alert is the most reliable (static page scraping) but covers only Amazon and Flipkart. Trending product detection depends on NLP accuracy over competitor channel text, which may misclassify product names (especially transliterated Hindi product names in regional posts).

**Fallback:** Commission rate alerts via manual update if scraping fails. Competitor spike alerts are the highest-value and lowest-risk sub-feature to launch first.

**Status:** ⚠️ PARTIAL — buildable but multi-component; no sub-feature is immediately fully reliable on day 1 |

---

### FEATURE 14 — RISK DETECTION

This feature has six sub-components.

| Sub-Feature | Required Data | Source | Confidence | Status |
|---|---|---|---|---|
| **Expired deal alert** | Price/stock of products linked in recent posts | Amazon/Flipkart API; AJIO/Nykaa: BLOCKED | HIGH (Amazon/Flipkart) / BLOCKED (AJIO/Nykaa) | ⚠️ PARTIAL |
| **Broken affiliate link** | HTTP status of own short URLs (amzn.to, fkrt.cc, grbn.in) | HTTP HEAD request to each URL | HIGH | ✅ BUILDABLE |
| **Engagement anomaly** | Rolling average views per post vs. recent posts | Telegram Bot API — own channel | HIGH | ✅ BUILDABLE |
| **Subscriber spike/drop** | Daily subscriber count delta | Telegram Bot API — getChatMembersCount | HIGH | ✅ BUILDABLE |
| **Competitor pressure** | Competitor posting frequency spike | t.me/s/ hourly scrape | MEDIUM | ⚠️ BUILDABLE with scraping dependency |
| **Affiliate link parameter mismatch** | Parse affiliate URLs from own posts; validate required params (affid, tag, pid) are present and correct | Own channel Bot API + URL parsing | HIGH | ✅ BUILDABLE |

**Overall Confidence: HIGH for 4 of 6 sub-features**

**Known Limitations:** The broken link check and parameter mismatch detection are the highest-confidence, simplest to build, and highest-value in preventing silent revenue loss. The expired deal alert is blocked for AJIO/Nykaa (same limitation as Feature 8). Subscriber spike detection via getChatMembersCount has rate limits — Telegram restricts how frequently this endpoint can be polled; daily snapshots are safe, hourly may hit limits.

**Status:** ✅ BUILDABLE for majority of sub-features. ⚠️ PARTIAL for expired deal (AJIO/Nykaa gap) |

---

### FEATURE 15 — PERFORMANCE RANKING

| Field | Detail |
|---|---|
| **Required Data** | Own channel full post history with: publish timestamp, message text, view count, forward count. Structured classification of each post: merchant, post type, emoji pattern, word count, time of day, day of week |
| **Data Source** | Telegram Bot API — full message history. View counts and forward counts included in message objects |
| **Collection Method** | One-time full history pull via Bot API (getHistory); ongoing incremental pull for new posts. NLP classifier assigns merchant, post type, emoji pattern for each message |
| **API or Scraping** | Telegram Bot API only — no external data needed |
| **Refresh Frequency** | Full history: one-time initial batch. New posts: near-real-time (poll every 15 minutes) |
| **Historical Availability** | **YES** — full Telegram channel history is accessible from day 1 of platform setup. All historical posts immediately available. |
| **Confidence** | **HIGH** for data availability. **MEDIUM** for classification accuracy (NLP on Telegram posts with emojis, Hindi transliteration, and deal-specific vocabulary requires domain-specific training or extensive prompt engineering) |
| **Known Limitations** | (1) View counts are cumulative totals — older posts have had more time to accumulate views. Must age-normalize: divide view count by days since posting to get views/day, or use only views within first 7 days (requires polling history from that period). (2) Click-through rate is unavailable — performance ranking uses views and forwards as proxies for engagement, not actual purchase intent or affiliate revenue. (3) NLP classification of posts with emoji-heavy formatting, branded product names, and Hindi transliteration will have higher error rates than standard English text classification. (4) Channel needs minimum 100 posts for pattern detection to have statistical meaning; fewer posts → noisy recommendations. |
| **Fallback Strategy** | Age-normalize views using (current views ÷ days live) as the comparison metric. For channels with fewer than 100 posts: show raw data without pattern analysis ("Not enough posts yet to identify patterns — analysis available after 100 posts") |
| **Status** | ✅ BUILDABLE |

---

### FEATURE 16 — PRICE BUCKET / THRESHOLD SELECTION

| Field | Detail |
|---|---|
| **Required Data** | Count of qualifying products at each price tier (₹299, ₹499, ₹999, ₹1,999) broken down by category for a given merchant |
| **Data Source** | Same as Feature 4 (product deal feed). Derived from product feed by filtering and counting |
| **Collection Method** | Aggregate query over the product feed database — count products per price band per category |
| **API or Scraping** | Derived from Feature 4 data — no additional data source needed |
| **Refresh Frequency** | Real-time query at collection creation time |
| **Historical Availability** | Available as soon as Feature 4 data exists |
| **Confidence** | Same as Feature 4: **HIGH** for Amazon/Flipkart, **BLOCKED** for AJIO/Nykaa/Croma |
| **Known Limitations** | Depends entirely on Feature 4 being operational. If Feature 4 is limited to Amazon/Flipkart, price bucket recommendations only work for Amazon/Flipkart collections |
| **Fallback Strategy** | Feature 4 fallback applies |
| **Status** | ✅ BUILDABLE (inherits Feature 4 status) — Amazon/Flipkart only |

---

### FEATURE 17 — POSTING FREQUENCY CALIBRATION

| Field | Detail |
|---|---|
| **Required Data** | Historical data: (date, post count for that day, average views per post for that day) — at least 90 data points (90 days) for regression |
| **Data Source** | Telegram Bot API — own channel message timestamps and view counts |
| **Collection Method** | Group posts by calendar date; compute daily post count and daily average view count per post; build time series; run correlation analysis between daily_post_count and avg_views_per_post |
| **API or Scraping** | Telegram Bot API only |
| **Refresh Frequency** | Weekly model update |
| **Historical Availability** | If channel has 90+ days of post history: immediately available. Channels younger than 90 days: partial data only |
| **Confidence** | **HIGH** for data availability (if channel history exists). **MEDIUM** for model reliability — frequency-engagement correlation is noisy (other variables confound it: sale events, trending topics, day of week) |
| **Known Limitations** | Correlation between frequency and engagement is confounded by many variables (sale events inflate both frequency and views simultaneously, creating false positive correlation). A naive regression will produce misleading recommendations without controlling for confounds. This is more complex than it appears in the AI Opportunity Analysis. Additionally, the "view dilution point" varies by subscriber base size — channels with 100K subscribers behave differently than channels with 5K subscribers. |
| **Fallback Strategy** | V1: simple descriptive statistics ("on days you posted 10+ times, average views per post was 2,100; on days you posted 5 times, it was 3,800"). Let operator interpret. V2: regression with confound controls once sufficient data exists |
| **Status** | ✅ BUILDABLE — with caveat that modeling accuracy requires 90+ days of history and careful statistical treatment |

---

### FEATURE 18 — CAMPAIGN BURST ORCHESTRATION

| Field | Detail |
|---|---|
| **Required Data** | Historical campaign burst data: for each burst event, the sequence of posts, inter-post intervals, view counts per post within the burst, and aggregate burst performance |
| **Data Source** | Telegram Bot API — own channel history. Competitor channel t.me/s/ — competitor burst events |
| **Collection Method** | Identify burst events in channel history (cluster of posts within a 4-hour window from same merchant/campaign). Extract post sequence, timestamps, view counts. Across all bursts, compute average view performance by position in sequence and by interval spacing |
| **API or Scraping** | Telegram Bot API (own). t.me/s/ scrape (competitor) |
| **Refresh Frequency** | Updated after each new burst event |
| **Historical Availability** | Own channel bursts: available from history. Competitor bursts: available from t.me/s/ (limited to visible history depth). Sample size: CRITICAL PROBLEM — most channels have run 5–20 burst campaigns in their lifetime. GrabOn's DELULU SALE (July 2026) is one data point. Statistical analysis requires minimum 30 burst events to identify reliable patterns. 5–20 events = insufficient for recommendation engine |
| **Confidence** | **LOW** — fundamental sample size problem. Burst campaigns are rare events; there is not enough historical data in any individual channel's history to build a reliable timing recommendation model |
| **Known Limitations** | The sample size problem is not solvable without aggregating across many channels (privacy concern) or waiting years for a single channel to accumulate 30+ burst events. The patterns identified from 5–10 bursts will be statistically unreliable — recommendations could be random noise rather than signal. Additionally, burst performance is heavily influenced by the sale being featured (Amazon GIF burst will outperform any internal campaign burst regardless of timing) — controlling for this confound is difficult with small samples. |
| **Fallback Strategy** | Instead of personalized burst recommendations: publish a fixed burst template based on observed competitor patterns (CouponzGuru's 60-minute fixed interval, GrabOn's 20-minute rapid burst) as a starting point. Add analytics to track burst performance over time and gradually improve recommendations as data accumulates. Do NOT promise AI-optimized burst orchestration on day 1. |
| **Status** | ⚠️ DELAYED — buildable in framework but recommendations will not be data-driven for at least 12–18 months of operation |

---

### FEATURE 19 — DAILY SUMMARY

| Field | Detail |
|---|---|
| **Required Data** | Own channel: today's posts, views per post, best/worst performer. Basic competitor activity (post count today) |
| **Data Source** | Telegram Bot API (own channel). t.me/s/ (competitor daily snapshot) |
| **Collection Method** | End-of-day batch: pull all posts from past 24 hours, compute stats, compare to rolling 30-day average, identify best/worst post, pull competitor post count |
| **API or Scraping** | Telegram Bot API + t.me/s/ scrape |
| **Refresh Frequency** | Daily (delivered at configured time, e.g., 11 PM) |
| **Historical Availability** | Available immediately — same data infrastructure as Feature 12 |
| **Confidence** | **HIGH** |
| **Known Limitations** | Same as Feature 12 — no revenue attribution without affiliate portal integration. View counts for posts made in the last few hours of the day will be early-stage; best/worst ranking based on same-day views will favor posts made earlier in the day |
| **Fallback Strategy** | Include caveat in summary: "Views for posts made after 8 PM are 6-hour counts only — final counts may differ" |
| **Status** | ✅ BUILDABLE |

---

### FEATURE 20 — FORECASTING

| Field | Detail |
|---|---|
| **Required Data** | (A) Time series: weekly post count, weekly total views, weekly avg views/post — at least 26 weeks for seasonal pattern detection. (B) Sale calendar (upcoming events). (C) Affiliate revenue per week — for revenue forecasting |
| **Data Source** | (A) Telegram Bot API — own channel historical posts. (B) Sale calendar (curated). (C) Affiliate portal — no standard API |
| **Collection Method** | (A) Weekly aggregation of Bot API data. (B) Pre-loaded calendar. (C) Manual operator input or portal CSV export |
| **API or Scraping** | (A) Telegram Bot API. (B) Static + periodic scrape. (C) No API — manual only |
| **Refresh Frequency** | Weekly model update |
| **Historical Availability** | View data: available from day 1 if channel has prior history. Seasonal patterns: require 52 weeks (1 year) of data to capture full seasonality (Diwali, Republic Day, etc.). Revenue data: operator-provided only |
| **Confidence** | **MEDIUM** for view count forecasting (view trends are forecastable with time-series methods). **LOW** for revenue forecasting (requires affiliate revenue data which is operator-manual-only). **LOW** for channels with less than 26 weeks of history (insufficient for seasonal patterns) |
| **Known Limitations** | Forecasting view counts is achievable for channels with 6+ months of history. Revenue forecasting requires affiliate revenue data that must be manually provided — no standard API exists across Amazon Associates, Flipkart Affiliate, and AJIO affiliate portals. Seasonal patterns (Diwali spike, New Year spike, summer slowdown) require at least one full year of data to detect reliably. New channels cannot use this feature meaningfully for the first 6–12 months. |
| **Fallback Strategy** | V1: Simple trend extrapolation (if the channel has been growing at X% per month, next week = current × growth_rate). V2: Sale event adjustment ("GIF historically produces 3–5x normal view volume across Indian deal channels — adjust forecast upward for GIF week"). V3: Full seasonal forecasting after 12 months of data |
| **Status** | ⚠️ DELAYED — buildable but meaningful only after 6+ months of channel history. Revenue component requires manual input |

---

## SECTION 3: CONSOLIDATED STATUS SUMMARY

| # | Feature | Status | Data Confidence | Blocker (if any) |
|---|---|---|---|---|
| 1 | Post Copy Generation | ✅ BUILDABLE | HIGH | Cold start: 60 posts for optimization (static templates work from day 1) |
| 2 | Affiliate Link Generation | ✅ / ⚠️ PARTIAL | HIGH (Amazon/Flipkart) / LOW (others) | No affiliate program for boAt, Zepto, Blinkit; operator must supply own credentials |
| 3 | Merchant Selection | ⚠️ PARTIAL | HIGH (Amazon/Flipkart) / BLOCKED (AJIO/Nykaa commission rates) | AJIO and Nykaa commission rates not publicly available |
| 4 | Product / Deal Selection | ⚠️ PARTIAL | HIGH (Amazon/Flipkart) / BLOCKED (AJIO, Nykaa, Croma, Zepto, Blinkit) | 5 of 10 target merchants inaccessible; price history requires 90-day cold start |
| 5 | Collection Curation | ⚠️ PARTIAL | HIGH (Amazon/Flipkart) / BLOCKED (fashion merchants) | Fashion-focused merchants (AJIO, Nykaa, Myntra) not auto-sourceable |
| 6 | Post Type Selection | ✅ BUILDABLE | HIGH | Cold start: 100 posts for reliable patterns |
| 7 | Posting Time Selection | ✅ BUILDABLE | MEDIUM (30-day polling required) | No retroactive view velocity; requires new polling infrastructure |
| 8 | Deal Expiry & Post Deletion | ⚠️ PARTIAL | HIGH (Amazon/Flipkart) / BLOCKED (AJIO, Nykaa, Croma) | Cannot monitor AJIO, Nykaa, Croma product status |
| 9 | Campaign Planning | ✅ BUILDABLE | HIGH (annual events) / LOW (flash sales) | Flash sales unpredictable; new channels have no historical baseline |
| 10 | Competitor Monitoring | ✅ BUILDABLE | MEDIUM (scraping dependency) | Relies on t.me/s/ — no official API; could break if Telegram changes structure |
| 11 | Deal Price Verification | ⚠️ PARTIAL | HIGH (Amazon/Flipkart/boAt) / BLOCKED (AJIO, Nykaa, Croma) | Cannot auto-verify AJIO and Nykaa prices |
| 12 | Weekly Executive Summary | ✅ BUILDABLE | HIGH (engagement) / LOW (revenue) | Revenue requires operator manual input; not automatable |
| 13 | Opportunity Detection | ⚠️ PARTIAL | MEDIUM | Multi-component; price drop alert blocked for first 90 days; AJIO commission alert blocked entirely |
| 14 | Risk Detection | ✅ BUILDABLE | HIGH (4 of 6 sub-features) | Expired deal monitoring has AJIO/Nykaa gap (same as Feature 8) |
| 15 | Performance Ranking | ✅ BUILDABLE | HIGH (data) / MEDIUM (classification) | Age normalization required; NLP classification accuracy on emoji-heavy Telegram posts is uncertain |
| 16 | Price Bucket Selection | ✅ BUILDABLE | HIGH (Amazon/Flipkart) / BLOCKED (fashion) | Inherits Feature 4 limitations |
| 17 | Posting Frequency Calibration | ✅ BUILDABLE | MEDIUM | Requires 90+ days of history; confound variables complicate regression |
| 18 | Campaign Burst Orchestration | ⚠️ DELAYED | LOW | Sample size insufficient for 12–18 months; do not promise AI optimization |
| 19 | Daily Summary | ✅ BUILDABLE | HIGH | Revenue excluded unless operator connects affiliate data |
| 20 | Forecasting | ⚠️ DELAYED | MEDIUM (views) / LOW (revenue) | Seasonal forecasting requires 12 months of data; revenue is manual-only |

---

## SECTION 4: THE MERCHANT DATA GAP — CRITICAL FINDING

**5 of 10 target merchants are programmatically inaccessible for product data:**

| Merchant | Block Type | Severity | Impact |
|---|---|---|---|
| AJIO | Akamai CDN — Access Denied | MAXIMUM | Fashion deal sourcing, price verification, expiry monitoring all blocked |
| Nykaa | Akamai CDN — Access Denied | MAXIMUM | Beauty/personal care deal sourcing blocked |
| Croma | Akamai CDN — Access Denied | HIGH | Electronics deal monitoring blocked |
| Zepto | robots.txt Disallow: / | MAXIMUM | Grocery deals entirely unreachable; no affiliate program |
| Blinkit | Cloudflare block | HIGH | Quick commerce deals blocked; no affiliate program |

**What this means for the platform:**

AJIO and Myntra together represent approximately 30–40% of the post volume in fashion-focused Indian deal channels (based on competitor channel analysis). Nykaa represents another 10–15% in beauty-focused channels. The platform can fully automate deal sourcing for Amazon and Flipkart (roughly 50% of content), but the fashion and beauty segments — which are high-commission, high-engagement categories — require manual operator input for sourcing and price verification.

This is not a solvable technical problem in the short term. Akamai CDN protection is enterprise-grade. The correct response is to design the platform's UX to make manual input for AJIO/Nykaa as frictionless as possible (fast forms, auto-fill from clipboard, bulk import) — not to promise programmatic access that cannot be delivered.

---

## SECTION 5: THE REVENUE DATA GAP — CRITICAL FINDING

**Affiliate revenue data is not programmatically accessible without custom integrations with each affiliate portal.**

Telegram does not provide click-through rate data. The platform cannot know:
- How many people clicked a specific post's link
- What % of those clicks resulted in a purchase
- How much commission was earned from a specific post

This data exists inside Amazon Associates, Flipkart Affiliate, and AJIO portals — all behind login walls with no standard public API. The only access path is:
1. Operator manually exports earnings report (CSV) from each portal
2. Operator uploads to the platform
3. Platform cross-references with post history by date/merchant

This creates a workflow gap: the platform can rank posts by views and forwards but cannot rank them by revenue. The "performance ranking" and "merchant selection" features will be engagement-based, not revenue-based, unless operators complete a manual data connection step.

**Revenue-blind analytics is a known limitation that must be communicated clearly to operators.** An operator seeing that their Amazon posts average 4,200 views does not know if that translates to ₹500 or ₹5,000 in commissions — that data is siloed in the affiliate portal.

---

## SECTION 6: COLD START REQUIREMENTS

Features that cannot deliver value on day 1 and require a data accumulation period:

| Feature | Cold Start Required | What Triggers Readiness |
|---|---|---|
| Post Copy Optimization (v2) | 60+ posts with engagement data | Channel has run 2+ months with the platform |
| Posting Time Selection (personalized) | 30 days of polling | Platform has been polling view counts for 30 days |
| Product Deal Selection (price history) | 90 days of price tracking | Platform has been running price snapshots for 90 days |
| Posting Frequency Calibration | 90 days of posting history | Channel has 90 days of daily post data |
| Campaign Burst Orchestration (AI) | 12–18 months of burst events | Not recommended to promise in product roadmap before month 18 |
| Forecasting (seasonal) | 12 months of channel data | Full annual cycle captured |

**Recommendation:** Surface cold start status to operators in the UI ("Performance Ranking: 47 of 100 posts needed"). Make it a progress indicator, not a locked feature — show partial data as it accumulates.

---

## SECTION 7: RECOMMENDED BUILD ORDER BASED ON DATA READINESS

Sequenced by: data availability on day 1 + strategic value.

**Build immediately (data exists now):**
1. Broken affiliate link detection (Feature 14 sub-component) — HTTP check, zero cold start, prevents silent revenue loss
2. Affiliate link parameter mismatch detection (Feature 14) — URL parsing, zero cold start, same
3. Post copy generation with static templates (Feature 1) — no data needed, immediate value
4. Affiliate link generation — Amazon/Flipkart (Feature 2) — API setup required, then works immediately
5. Daily and weekly summary — engagement metrics (Features 12, 19) — Bot API, works from day 1
6. Competitor monitoring — post frequency and content (Feature 10) — t.me/s/ scraping works now

**Build after 30 days of data:**
7. Post type selection recommendations (Feature 6) — needs 100 posts
8. Posting time selection — personalized (Feature 7) — needs 30 days of polling
9. Performance ranking (Feature 15) — needs 100+ posts, age-normalized
10. Opportunity detection — competitor spike + category gap alerts (Feature 13)

**Build after 90 days of data:**
11. Deal price verification — Amazon/Flipkart (Feature 11)
12. Deal expiry monitoring — Amazon/Flipkart (Feature 8)
13. Merchant selection — Amazon/Flipkart commission comparison (Feature 3)
14. Product deal selection — Amazon/Flipkart auto-sourcing (Feature 4)
15. Collection curation — Amazon/Flipkart (Feature 5)
16. Posting frequency calibration (Feature 17)

**Build after 6–12 months:**
17. Campaign planning with historical performance (Feature 9)
18. Risk detection — full suite (Feature 14)
19. Forecasting — trend-based (Feature 20)
20. Campaign burst orchestration — framework only; AI recommendations deferred (Feature 18)

---

*This document reflects data availability as confirmed in research conducted through July 2026. API terms, platform protections, and data availability can change. Amazon PA-API deprecation (May 15, 2026) and its replacement by Creators API is the most recent significant change that must be tracked.*
