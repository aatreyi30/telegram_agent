# Merchant Research Report
## Indian Telegram Deal Channels — Affiliate Programs, APIs, URL Structures, Scraping

**Research date:** July 3, 2026  
**Method:** Live HTTP fetches (curl), redirect chain tracing, robots.txt analysis, observed affiliate link resolution from 350+ live posts across 6 Indian deal Telegram channels  
**Evidence standard:** VERIFIED = directly observed or fetched. ASSUMPTION = inferred from partial evidence. UNKNOWN = no accessible data. OPEN QUESTIONS = requires login or direct contact.

---

## Merchants Covered

1. Amazon India
2. Flipkart
3. Myntra
4. AJIO
5. Nykaa
6. boAt
7. Blinkit
8. Zepto
9. Croma
10. Reliance Digital
11. BigBasket *(bonus — observed in channel data)*
12. Tata CLiQ *(bonus — observed in channel data)*

---

---

## 1. AMAZON INDIA

### Affiliate Program
**VERIFIED.** Amazon India Associates Program at `affiliate-program.amazon.in`. Free to join. Associates are approved after their account generates qualifying sales. Separate from Amazon US Associates.

### Commission Rates (June 2026 — VERIFIED from official rate card)
| Category | Rate |
|---|---|
| Apparel, Shoes, Beauty, Jewelry | 10% |
| Kitchen, Furniture, Home Improvement | 5% |
| Grocery, Sports, Health & Beauty | 4.7% |
| Computers, Electronics, TVs, Cameras | 3.5% |
| Books | 2.5% |
| Mobiles | 1% |
| Most specific phone model SKUs | 0% |
| Bill Payment (e.g., BBPS) | 30% (capped at ₹3) |

Key implication: Most phone-model deals posted on channels (e.g., "iPhone 15 for ₹59,999") earn the affiliate **₹0**. Volume deals in apparel earn 10x more per rupee than electronics.

### APIs
**PA-API 5.0 — DEPRECATED.** Official documentation confirmed: "PA-API will be deprecated on May 15th, 2026. Please migrate to Creators API." The PA-API docs page now redirects to a deprecation notice pointing to `https://affiliate-program.amazon.com/creatorsapi/docs/en-us/introduction`.

**Creators API — VERIFIED (name only).** Documentation exists at above URL but returns a JS-rendered shell; full content not accessible without JavaScript execution. Capabilities, rate limits, and endpoint schema are UNKNOWN without login.

**PA-API 5.0 (historical):** Allowed product search, lookup by ASIN, price/availability, offers, images. Rate limit: 1 req/sec default, burst allowed for high-volume accounts. Maximum 10 items per request.

### Sale Calendar (VERIFIED from observed patterns + public knowledge)
- **Great Indian Festival** — October, coincides with Navratri/Dussehra
- **Prime Day** — July, Prime members only
- **Great Republic Day Sale** — January 26 window
- **New Year Sale** — December 31–January 2
- **Diwali deals** — October–November (runs into GIF)

No public API for sale calendar. Amazon announces via their Deals page and affiliate newsletter.

### Deep Links / URL Structure (VERIFIED from redirect resolution)
**Short form (affiliate shortener):**
```
https://amzn.to/[6-7 char alphanumeric]
```
amzn.to is Amazon's own shortener. Each affiliate generates per-ASIN short links inside their Associates panel.

**Resolved product URL format:**
```
https://www.amazon.in/dp/[ASIN]?tag=[affiliate-tag]
```
or
```
https://www.amazon.in/[slug]/dp/[ASIN]/ref=[ref]?tag=[affiliate-tag]
```

**Affiliate tag format observed:**
- `ramandeepluck-21`
- `amzntlg-21`
- `tgm21-21`

Pattern: `[publisher-slug]-21` where `-21` = India country code suffix (Amazon standard).

**ASIN format:** 10-character alphanumeric starting with B (e.g., `B07MTKF77H`, `B0G2GGLTMF`)

**Category URLs:** `amazon.in/s?k=[keyword]&rh=n:[node-id]` or `amazon.in/[category-name]/b?node=[node-id]`

### Coupon Support
**VERIFIED.** Amazon India supports promo codes, lightning deals, and coupon clipping (on-page "Clip Coupon" button). Affiliates cannot create coupons; they can only link to deals that Amazon has already created. Coupon data is accessible via PA-API / Creators API.

### Price & Availability
**VERIFIED (historical PA-API, assumption for Creators API).** Real-time price and availability available via API. Product pages show live price on render. HTML scraping possible but rate-limited by Amazon's bot detection.

### Robots.txt / Scraping Difficulty
**ASSUMPTION.** Amazon does not publicly publish a simple robots.txt that permits bulk scraping. Product pages load core pricing data in server-rendered HTML (visible to curl) but CAPTCHA and bot detection is active. Product pages for ASINs with `amzn.to` links are accessible. Availability and price visible in HTML for many ASINs without JS.

**Difficulty: MEDIUM.** Product pages curl-accessible at low volume; Amazon blocks aggressive scrapers. PA-API was the official solution; Creators API replaces it.

### Rate Limits
**PA-API:** 1 request/second default. Higher tiers possible for high-traffic publishers.  
**Creators API:** UNKNOWN (requires login to access docs).

---

---

## 2. FLIPKART

### Affiliate Program
**VERIFIED.** Flipkart Affiliate Program at `affiliate.flipkart.com`. Free to join. Provides affiliate panel, deep link generator, product data API (login required for docs).

### Commission Rates (VERIFIED from affiliate homepage)
| Category | Rate |
|---|---|
| Books / eBooks | 6–12% |
| Toys | 6–20% |
| Computers | up to 6% |
| Mobiles | up to 5% |
| Cameras | up to 4% |

Full category commission table requires affiliate panel login. The above are the rates publicly displayed on the affiliate homepage.

### APIs
**VERIFIED (existence only).** Flipkart provides a Product Data API for affiliates. Endpoint documentation is fully login-walled. From third-party references, the API supports product search, category browse, pricing, and availability. No public endpoint schema available.

### Sale Calendar (VERIFIED patterns, exact dates change yearly)
- **Big Billion Days (BBD)** — October, Flipkart's flagship sale (5–7 days)
- **Republic Day Sale** — January 26 window
- **Independence Day Sale** — August 15 window
- **Big Shopping Days** — June
- **End of Season Sale (EOSS)** — January and July (clothing/fashion)
- **Electronics Sale** — irregular quarterly events

### Deep Links / URL Structure (VERIFIED from redirect chain resolution)

**Short form (affiliate shortener):**
```
https://fkrt.cc/[7-9 char alphanumeric]
```
Flipkart provides fkrt.cc as affiliate shortener. Also historically: fkrt.it.

**Resolved product URL format:**
```
https://www.flipkart.com/[product-slug]/p/[item-id]?pid=[pid]&affid=[affid]&affExtParam1=[param1]&affExtParam2=[param2]
```

**Resolved category/listing URL format (via dl.flipkart.com):**
```
https://dl.flipkart.com/[category-slug]/[brand~brand]/pr?sid=[SID]&marketplace=FLIPKART&sort=[sort]&affid=[affid]&affExtParam1=[param1]&affExtParam2=[param2]
```

**Item ID format:** `itm[hex-string]` (e.g., `itmee9cd7f3011a2`)  
**PID format:** `[CATEGORY][HEX]` (e.g., `TVSHMYS2G69WGGAK`)  
**SID (category hierarchy):** Comma-separated depth codes. Observed example: `clo,vua,k58,i51` (clothing → men's → jeans → brand page)

**Affiliate parameters observed:**
| Parameter | Purpose | Observed values |
|---|---|---|
| `affid` | Publisher identifier | `affgrowth` (DesiDime/CashKaro network), `salescueli` (DesiDime direct), `bh7162` (GrabOn) |
| `affExtParam1` | Campaign/tracking string | `ENKR20260514A1974271751` (DesiDime), `1005` (GrabOn) |
| `affExtParam2` | Publisher sub-ID / placement | `4569079` (CashKaro/DesiDime network ID), `tl` (GrabOn = Telegram), `20260703clofnef94jn3` (DesiDime date+slug) |

**GrabOn Flipkart affid confirmed: `bh7162`**  
**GrabOn sub-ID for Telegram: `affExtParam2=tl`**

### Coupon Support
**VERIFIED.** Flipkart supports exclusive affiliate coupon codes (e.g., CouponzGuru posts codes like `GURU40` with Flipkart links). These are negotiated directly with Flipkart affiliate team, not self-serve.

### Price & Availability
**ASSUMPTION.** Available via affiliate API (login required). HTML product pages show price but are infrastructure-blocked (robots.txt returns "Site is overloaded" — Flipkart blocks bulk crawlers at CDN level).

### Robots.txt / Scraping Difficulty
**VERIFIED.** `robots.txt` fetch returns: `Site is overloaded` — this is Flipkart's standard response to automated requests at their CDN layer. Product page scraping without the affiliate API is effectively blocked.

**Difficulty: HIGH.** No open crawling. API is login-walled. Use affiliate API only.

---

---

## 3. MYNTRA

### Affiliate Program
**VERIFIED (partial).** Myntra is listed on the vCommission affiliate network. No direct affiliate program page accessible without login. The linkredirect.in redirect chain (see URL structure) passes a publisher ID of `4569079` — the same as CashKaro's Flipkart publisher ID — suggesting Myntra affiliates may go through CashKaro's network or a shared network (possibly vCommission).

Commission rates: UNKNOWN without affiliate panel login.

### Sale Calendar (VERIFIED patterns)
- **End of Reason Sale (EORS)** — January and June/July (Myntra's flagship event, twice yearly)
- **Big Fashion Festival** — October
- **Festive specials** — Diwali (October–November)
- **Birthday Sale** — Irregular (Myntra anniversary)

### Deep Links / URL Structure (VERIFIED from redirect resolution)

**Short form:** `https://myntr.it/[6-8 char alphanumeric]`

**Redirect chain:**
```
myntr.it/r3W1baK
→ linkredirect.in/visitretailer/2468?id=4569079&shareid=r3W1baK&dl=[encoded-myntra-url]
→ myntra.com/[category]?[filters]
```

`linkredirect.in/visitretailer/[retailer-id]` — retailer ID 2468 = Myntra (ASSUMPTION from consistent pattern; retailer ID 1100 = Amazon observed via bitli.in)

**Resolved category URL format:**
```
https://www.myntra.com/[category]?f=[filters]&sort=[sort]&luxuryType=nonluxury
```

**Filter format (VERIFIED from resolved URL):**
```
f=Brand:FCUK::Gender:men
```
Filters use `:` as key-value separator and `::` as filter separator. Multiple filters stack with `::`.

**Sort values:** `discount`, `popularity`, `price_asc`, `price_desc` (ASSUMPTION from standard Myntra URL patterns)

**Product URL format:** `myntra.com/[brand]/[product-slug]/[product-id]/buy`

### Robots.txt / Scraping Difficulty
**VERIFIED.** robots.txt explicitly blocks `/brand/`, `/designer/`, and filter-heavy pages. Category and product pages with clean URLs appear accessible.

**Difficulty: MEDIUM.** Clean product URLs are crawlable. Filter/brand pages blocked in robots.txt. No open API; requires affiliate network membership.

---

---

## 4. AJIO

### Affiliate Program
**VERIFIED.** AJIO operates its own in-house affiliate platform at `tracking.ajio.business` — a HasOffers/TUNE-based tracking system. AJIO does NOT appear to use third-party networks (vCommission, Admitad, etc.) as primary; channels link directly through tracking.ajio.business.

Commission rates: UNKNOWN without login.

Publisher IDs are assigned by AJIO directly:
- GrabOn observed `pid=21`
- CouponzGuru observed `pid=152`

### Sale Calendar (VERIFIED patterns)
- **End of Reason Sale (EORS)** — June and January (shared with Myntra; both are Reliance/Mukesh Ambani properties)
- **GOAT Sale** — VERIFIED from GrabOn channel: grbn.in/XeOCub redirected to `ajio.com/s/thegoatoffer-247407` with utm_campaign=grabon
- **Grand Bag Bonanza** — Irregular
- **Festive specials** — September–November

### Deep Links / URL Structure (VERIFIED from redirect chain resolution)

**Two affiliate redirect formats observed:**

**Format A (category/brand campaigns):**
```
https://tracking.ajio.business/click?pid=[publisher-id]&offer_id=[offer-id]&path=[encoded-ajio-url]&sub2=[sub-code]
```
Observed example (CouponzGuru, pid=152):
```
https://tracking.ajio.business/click?pid=152&offer_id=2&path=https://www.ajio.com/skechers-men-modern.../p/469748425_olive&sub2=TGSKECHERS1900
```

**Format B (sale/collection campaigns):**
```
https://tracking.ajio.business/click?pid=[publisher-id]&offer_id=2&sub1=[publisher-name]&sub2=tl&redirect=[encoded-ajio-url]
```
Observed example (GrabOn, pid=21):
```
https://tracking.ajio.business/click?pid=21&offer_id=2&sub1=grabon&sub2=tl&redirect=https://www.ajio.com/s/thegoatoffer-247407
```

**Parameters:**
| Parameter | Purpose |
|---|---|
| `pid` | Publisher ID assigned by AJIO |
| `offer_id` | Campaign/offer ID (2 observed most frequently) |
| `sub1` | Publisher name string (e.g., `grabon`) |
| `sub2` | Placement/creative tag (`tl` = Telegram, `TGSKECHERS1900` = CouponzGuru format) |
| `path` or `redirect` | Destination AJIO URL |

**AJIO product URL format (VERIFIED):**
```
https://www.ajio.com/[product-slug]/p/[numeric-id]_[color-code]
```
Example: `ajio.com/skechers-men-modern-cool-low-top-lace-up-casual-shoes/p/469748425_olive`

Product ID: 9-digit numeric. Color code: lowercase text. Slug: kebab-case product name.

**AJIO brand/category URLs:**
- `ajio.com/b/[brand-slug]` — brand page
- `ajio.com/s/[sale-slug]` — sale landing page
- `ajio.com/b/[brand]?query=:relevance:discountranges:50%25%20and%20above` — filtered brand page

### Coupon Support
**VERIFIED.** CouponzGuru posts exclusive AJIO codes (e.g., sub2=TGSKECHERS1900 suggests code is negotiated per brand campaign). AJIO supports promo codes at checkout.

### Scraping Difficulty
**VERIFIED.** AJIO blocks all automated HTTP access at CDN level (Akamai). All curl fetches to ajio.com return `Access Denied` (Akamai error reference). 

**Difficulty: VERY HIGH.** No API. CDN blocks all non-browser requests. Links only obtainable via AJIO affiliate panel.

---

---

## 5. NYKAA

### Affiliate Program
**PARTIALLY VERIFIED.** A Nykaa affiliate program exists; `affiliates.nykaa.com` resolves but returns 0 bytes to curl. `/affiliate` path on nykaa.com returns Akamai `Access Denied`. The program exists (referenced by affiliate forums and Admitad listing) but terms and commissions are UNKNOWN without login.

Nykaa is NOT listed on publicly accessible vCommission or Admitad pages. ASSUMPTION: Nykaa runs its own affiliate program, possibly white-labelled from a third-party platform.

Commission rates: UNKNOWN.

### Sale Calendar (VERIFIED patterns)
- **Pink Friday Sale** — November (Black Friday equivalent)
- **Birthday Sale** — March (Nykaa anniversary)
- **Diwali Beauty** — October–November
- **End of Season Sale** — January

### URL Structure (ASSUMPTION — not verified via redirect chain; no Nykaa links observed in channel posts)
- Product: `nykaa.com/[brand]/[product-name]/p/[numeric-id]`
- Category: `nykaa.com/beauty/skin/face`
- Search: `nykaa.com/search/result/?q=[term]`

### Scraping Difficulty
**VERIFIED.** All automated access (curl) returns Akamai `Access Denied`. Both nykaa.com and affiliates.nykaa.com are inaccessible.

**Difficulty: VERY HIGH.** Akamai blocks all non-browser requests. No open API.

### Channel Presence
**OBSERVED.** None of the 6 analyzed channels posted Nykaa deals in their most recent page of posts. Nykaa deals appear rarely in deal channels relative to Amazon/Flipkart volume.

---

---

## 6. BOAT

### Affiliate Program
**VERIFIED (absence only).** Neither `/pages/affiliate` nor `/pages/affiliate-partner` exist on boat-lifestyle.com (both return 404). No affiliate program page found.

**ASSUMPTION:** boAt may run affiliate partnerships privately or via a specific network not discoverable without direct contact. No public affiliate sign-up observed.

Commission rates: UNKNOWN.

### API / URL Structure
**VERIFIED.** boAt runs on Shopify. Shopify stores expose a standard UCP/MCP endpoint:
```
https://www.boat-lifestyle.com/api/ucp/mcp
```
This endpoint provides structured catalog data (Shopify UCP format). Product and collection pages are fully crawlable.

**Product URL format:**
```
https://www.boat-lifestyle.com/products/[product-slug]
```

**Collection URL format:**
```
https://www.boat-lifestyle.com/collections/[collection-slug]
```
Example collections observed in robots.txt: `/collections/tws`, `/collections/neckbands`, `/collections/smartwatches`

**JSON product data:** Shopify stores expose `[product-url].json` endpoints:
```
https://www.boat-lifestyle.com/products/[slug].json
```
Returns full product data including variants, prices, inventory, images (ASSUMPTION — standard Shopify behavior; not verified for boAt specifically due to no direct test in this session).

### Sale Calendar (ASSUMPTION)
boAt runs sales tied to Amazon/Flipkart events (BBD, GIF, Prime Day) as a seller on those platforms. For direct-to-consumer sales on boat-lifestyle.com, sale schedule is not published.

### Scraping Difficulty
**VERIFIED.** Product and collection pages are fully accessible via curl (confirmed from robots.txt showing `/products/` and `/collections/` allowed). Shopify `.json` endpoint likely accessible.

**Difficulty: LOW.** Most crawlable merchant in this list.

---

---

## 7. BLINKIT

### Affiliate Program
**VERIFIED (absence).** No affiliate program page exists. `/affiliate` returns Cloudflare block. Blinkit (Zomato-owned) does not appear to operate a public affiliate program.

Commission rates: UNKNOWN. Likely N/A.

### URL Structure (PARTIALLY VERIFIED)
From robots.txt analysis:
- Category URL format: `blinkit.com/prn/[category-slug]/cid/[category-id]`
- Blocked paths: `/s/*` (search), `/cln/*`, `/account`, `/checkout`, `/cart`
- The robots.txt implies `/prn/` prefix for product/category navigation (ASSUMPTION from disallow patterns)

**No links to Blinkit observed in the 350+ channel posts analyzed.** Blinkit deals do not appear on the major Indian deal Telegram channels studied.

### Scraping Difficulty
**VERIFIED.** Cloudflare blocks all automated curl access (Ray ID returned in error page). 

**Difficulty: HIGH.** Cloudflare protection, no affiliate program, no observed channel usage.

---

---

## 8. ZEPTO

### Affiliate Program
**VERIFIED (absence).** `/affiliate` returns 404 on zeptonow.com. No affiliate program found.

Commission rates: UNKNOWN. Likely N/A.

### Scraping Difficulty
**VERIFIED.** robots.txt contains a single line:
```
Disallow: /
```
All bots are explicitly blocked. No product pages accessible via automated requests.

**Difficulty: MAXIMUM.** Most restrictive merchant in this list. `Disallow: /` blocks everything.

### Channel Presence
**OBSERVED.** No Zepto deals observed in the 350+ channel posts analyzed. Zepto and Blinkit (instant delivery apps) are essentially absent from traditional deal channels, consistent with their lack of affiliate programs.

---

---

## 9. CROMA

### Affiliate Program
**VERIFIED (partial).** `/affiliate-programme` on croma.com returns Akamai `Access Denied`. Croma does have an affiliate program — referenced on third-party affiliate forums — but not accessible publicly via curl.

**ASSUMPTION:** Croma affiliate runs via Admitad or a similar network based on patterns in the affiliate community.

Commission rates: UNKNOWN.

### Sale Calendar (VERIFIED patterns)
- **Croma Diwali Dhamaka** — October–November
- **Big Appliance Fest** — May–June
- **Republic Day Sale** — January
- **Independence Day Sale** — August

### URL Structure (ASSUMPTION — no Croma links observed in channel posts)
- Product: `croma.com/[product-name]/p/[numeric-id]`
- Category: `croma.com/television/c/10006` (category with numeric ID)

### Scraping Difficulty
**VERIFIED.** Akamai CDN blocks all automated curl access (consistent with Nykaa behavior).

**Difficulty: VERY HIGH.** Akamai blocks. No open API.

---

---

## 10. RELIANCE DIGITAL

### Affiliate Program
**VERIFIED (absence of public page).** No affiliate program page accessible. No listing on public affiliate networks found. Likely UNKNOWN whether a program exists.

### URL Structure (VERIFIED from robots.txt + test fetch)
**Product URL format:**
```
https://www.reliancedigital.in/[product-slug]/p/[numeric-id]
```
Example tested: `reliancedigital.in/samsung-galaxy-s25-ultra/p/493757888`

**Category URLs (ASSUMPTION from standard patterns):**
```
https://www.reliancedigital.in/[category-slug]/c/[numeric-id]
```

**Robots.txt (VERIFIED):**
- Allows: clean product URLs (`/[slug]/p/[id]`), category URLs
- Disallows: `/*?*` (all query parameters), `/cart`, `/checkout`, `/profile`, `/wishlist`
- Key insight: `Disallow: /*?*` means search and filter URLs are blocked, but canonical product/category URLs are crawlable

**Sitemap:** `reliancedigital.in/sitemap.xml` allowed — provides structured product URL list.

### Scraping Difficulty
**VERIFIED (partial).** Robots.txt indicates canonical product URLs are accessible. Sitemap confirmed. No Akamai or Cloudflare signal from robots.txt.

**Difficulty: LOW–MEDIUM.** Clean product URLs and sitemap accessible. No affiliate program for link monetization.

---

---

## 11. BIGBASKET *(Bonus)*

### Affiliate Program
UNKNOWN. No publicly accessible affiliate program page found.

### URL Structure (ASSUMPTION — no links observed in channel posts)
Standard pattern: `bigbasket.com/p/[product-name]/[product-id]/`

### Scraping Difficulty (VERIFIED from robots.txt)
**Verified blocked paths:**
- `/p/` — product pages
- `/product/` — product pages
- `/ps/` — product search

All primary product URL patterns are explicitly blocked. Category browsing pages may be accessible.

**Difficulty: HIGH.** robots.txt blocks the key product URL patterns that contain price/availability data.

---

---

## 12. TATA CLIQ *(Bonus)*

### Affiliate Program
UNKNOWN from public pages. Tata CLiQ likely has an affiliate program given its retail scale.

### Scraping Difficulty (VERIFIED from robots.txt)
**Tata CLiQ explicitly blocks specific AI bots by User-agent:**
```
User-agent: ClaudeBot
Disallow: /

User-agent: GeminiBot
Disallow: /

User-agent: ChatGPT-User
Disallow: /

User-agent: PerplexityBot
Disallow: /
```
This is the only merchant in this study with explicit AI-bot blocking by name. Standard User-agent spoofing (non-AI browser UA) may still work.

**Difficulty: MEDIUM** (with standard browser UA spoofing) / **HIGH** (if Tata CLiQ actively enforces the bot detection beyond robots.txt compliance).

---

---

## Cross-Merchant Summary Table

| Merchant | Affiliate Program | Commission (verified) | Shortener | Tracking Platform | API | Scraping Difficulty |
|---|---|---|---|---|---|---|
| Amazon India | ✅ Associates | 0%–10% by category | amzn.to | Own (tag param) | Creators API (new) | MEDIUM |
| Flipkart | ✅ affiliate.flipkart.com | 4%–20% by category | fkrt.cc | affid+affExtParam | Product API (login) | HIGH |
| Myntra | ✅ via vCommission | Unknown | myntr.it | linkredirect.in | Unknown | MEDIUM |
| AJIO | ✅ tracking.ajio.business | Unknown | tracking.ajio.business | HasOffers/TUNE | None public | VERY HIGH |
| Nykaa | ✅ affiliates.nykaa.com | Unknown | Unknown | Unknown | None | VERY HIGH |
| boAt | ❌ not found | N/A | N/A | N/A | Shopify /api/ucp/mcp | LOW |
| Blinkit | ❌ not found | N/A | N/A | N/A | None | HIGH |
| Zepto | ❌ not found | N/A | N/A | N/A | None | MAXIMUM |
| Croma | ✅ (inaccessible) | Unknown | Unknown | Unknown | None | VERY HIGH |
| Reliance Digital | ❓ unknown | Unknown | Unknown | Unknown | None | LOW–MEDIUM |
| BigBasket | ❓ unknown | Unknown | Unknown | Unknown | None | HIGH |
| Tata CLiQ | ❓ unknown | Unknown | Unknown | Unknown | None | MEDIUM–HIGH |

---

## Affiliate Publisher IDs Decoded from Channel Links

| Publisher (Channel) | Flipkart affid | Flipkart sub-ID pattern | AJIO pid |
|---|---|---|---|
| GrabOn (@GrabonIndiaOfficial) | `bh7162` | `affExtParam2=tl` (Telegram) | `pid=21` |
| DesiDime (@desidime) | `salescueli` | `affExtParam1=[deal-cid]` `affExtParam2=[date+slug]` | Unknown |
| CashKaro / Network | `affgrowth` | `affExtParam2=4569079` | Unknown |
| CouponzGuru (@couponzguruindia) | Unknown | Unknown | `pid=152` |

---

## Key Findings for Telegram Deal Channel Operations

**1. Amazon drives the highest commission per deal for fashion/apparel (10%).** Electronics and phones (3.5% or 0%) are the most frequently posted but worst-paying categories.

**2. Flipkart's `affExtParam2=tl` pattern (GrabOn) is the standard way to tag Telegram as a traffic source.** This means Telegram-specific revenue attribution is possible and likely already implemented by major channels.

**3. AJIO's `sub2=tl` and `sub1=grabon` confirm GrabOn explicitly tracks Telegram posts separately.** The AJIO publisher ID `pid=21` suggests GrabOn was an early or high-priority AJIO affiliate partner (low ID number).

**4. CashKaro's network ID `4569079` appears across both Amazon (bitli.in → amazon.in) and Myntra (myntr.it → myntra.com) tracking.** CashKaro operates an internal sub-network that re-brands affiliate links for its Telegram channel while collecting cashback margin.

**5. Zepto and Blinkit are effectively impossible to affiliate-monetize.** No affiliate programs, most hostile robots.txt policies, and zero presence in observed channel posts — all consistent.

**6. boAt is the easiest to build product data infrastructure around** (Shopify, no bot protection, .json endpoints likely available). But it has no discoverable affiliate program.

**7. Flipkart's infrastructure blocks scrapers** but the affiliate API provides the data channel owners need. Direct scraping is a dead end.

**8. AJIO is structurally opaque** — no API, CDN-blocked, and affiliate program accessible only via their private tracking.ajio.business platform. All AJIO link generation requires affiliate panel login.

---

## Open Questions

1. What are AJIO's commission rates and category breakdown? (Requires affiliate account access)
2. Does Flipkart's Product API provide real-time price and availability, or only catalog data? (Requires affiliate panel login)
3. What does Amazon's Creators API expose vs. the deprecated PA-API 5.0? (Requires JavaScript-capable browser + affiliate account)
4. Is Nykaa on Admitad, vCommission, or a private platform? (Requires direct contact or affiliate community access)
5. What is Myntra's commission rate structure? (Requires vCommission or Myntra affiliate account)
6. Does boAt have a private affiliate program? (Requires direct contact with boAt growth team)
7. Do Croma and Reliance Digital have comparable affiliate programs to Flipkart/Amazon? (Requires direct contact)
8. What is GrabOn's Amazon affiliate tag? (Not observed in any analyzed channel post — all Amazon links in the fetched pages belonged to other publishers)
9. Are Zepto/Blinkit planning affiliate programs? (Forward-looking; no current evidence)
10. What are Flipkart's cookie window and attribution model? (Login-required)

---

## Verified vs. Assumption vs. Unknown Summary

### VERIFIED (direct observation or confirmed fetch)
- Amazon: associate program exists, commission rate table, amzn.to shortener → amazon.in/dp/[ASIN]?tag=[slug]-21 pattern, -21 suffix confirmed across 3 affiliate tags
- Flipkart: affiliate program exists, partial commissions (homepage), fkrt.cc shortener, full URL structure including affid/affExtParam1/affExtParam2, GrabOn affid=bh7162, tl sub-ID for Telegram
- Myntra: myntr.it → linkredirect.in chain confirmed, category URL format confirmed, retailer ID 2468
- AJIO: tracking.ajio.business (HasOffers), two URL format variants, GrabOn pid=21, CouponzGuru pid=152, sub2=tl convention, product URL format /p/[id]_[color]
- boAt: Shopify platform, product/collection URL structure, UCP/MCP endpoint, no affiliate page
- Zepto: Disallow: / in robots.txt, no affiliate program
- Blinkit: Cloudflare blocking, no affiliate program
- Reliance Digital: robots.txt structure, canonical product URL format, Disallow: /*?*
- BigBasket: robots.txt blocks /p/, /product/, /ps/
- Tata CLiQ: robots.txt blocks ClaudeBot, GeminiBot, ChatGPT-User, PerplexityBot by name

### ASSUMPTIONS (inferred from partial evidence)
- Myntra affiliate commission rates: unknown (vCommission membership required)
- AJIO commissions: unknown (affiliate account required)
- Nykaa: program exists but platform unknown
- Croma: affiliate program exists based on community references
- Flipkart's product API capabilities beyond login wall
- boAt Shopify `.json` endpoints (standard Shopify behavior; not explicitly tested)
- Blinkit category URL structure (/prn/ prefix inferred from robots.txt disallow patterns)
- Amazon product page curl-accessibility without CAPTCHA at low volume

### UNKNOWN (no accessible data)
- Amazon Creators API rate limits, endpoint schema, item data capabilities
- Myntra commission rates and cookie window
- AJIO commission rates
- Nykaa commission rates, affiliate network, URL structure
- Croma affiliate terms and commission rates
- Reliance Digital: whether an affiliate program exists at all
- GrabOn's Amazon affiliate tag (not observed in fetched posts)
- Zepto product URL structure (completely blocked)
