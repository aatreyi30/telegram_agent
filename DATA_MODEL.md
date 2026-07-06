# Data Model — what every table is for

Grouped by the phase that owns it. This answers "why does this table exist?" — the
concern raised about the `scheduled_posts` ("automation") table. Everything is SQLite;
new columns are added by `db/migrate.py` (additive `ALTER TABLE`), tables by
`Base.metadata.create_all`.

## Organization (multi-tenancy — `db/models_org.py`)
| Table | Purpose |
|---|---|
| `organizations` | A tenant (e.g. **GrabOn**). Holds the org's affiliate provider + settings (shortener URL, tags, owned/competitor handles). Provider resolution reads this first, then `.env`. |
| `users` | People in an org, with a role (owner/editor/viewer). Structural — no login yet. |
| `channels`.`org_id`, `.kind` | Links each Telegram channel to its org and labels it `owned` vs `competitor`. |

## Ingestion (Phase 1 — `db/models.py`)
| Table | Purpose |
|---|---|
| `channels` | Owned Telegram channels (id, handle, subscriber count, `can_view_stats`). |
| `posts` | Every collected message: text, media flags, links, and **views/forwards/reactions** (views are our main metric as a member). |
| `post_metric_snapshots` | Point-in-time metric captures per post (age + views) for velocity analysis. |
| `channel_stat_snapshots` | **Admin-only** broadcast stats (followers, reach, notifications). Empty while we're a member; filled by `collection/telegram_stats.py` once admin. |
| `competitors`, `competitor_posts` | Public competitor channels + their posts (scraped from t.me/s: rounded views, no reactions). |
| `merchants`, `merchant_products`, `product_price_snapshots`, `affiliate_links` | Merchant catalog + price history (buildable merchants only). |
| `raw_snapshots` | Content-addressed raw payloads (audit/provenance). |
| `collection_jobs`, `collection_events` | Job lifecycle + the event log. |

## Normalization (Phase 2 — `db/models_normalization.py`)
| Table | Purpose |
|---|---|
| `normalized_posts` | Cleaned, structured view of each post (source_type owned/competitor, primary merchant, flags). |
| `extracted_prices`, `extracted_coupons`, `extracted_links` | Structured facts pulled from post text. |

## Classification (Phase 3 — `db/models_classification.py`)
| Table | Purpose |
|---|---|
| `post_type_clusters` | Unsupervised post-type clusters (descriptors like "many-links · multi-deal"). |
| `post_classifications` | Which cluster each post belongs to. |

## Intelligence (Phases 4–8)
| Table | Purpose |
|---|---|
| `merchant_profiles`, `merchant_metric_windows`, `merchant_opportunities` | Per-merchant performance + opportunities (Phase 4). |
| `competitor_profiles`, `competitor_benchmarks`, `competitor_signals` | Competitor behaviour + owned-vs-competitor comparisons (Phase 5). |
| `channel_style_profiles`, `post_type_performance`, `learning_records` | Learned style, ranked post-type performance, evidence-backed learnings incl. emoji/timing (Phase 6). |
| `growth_strategies`, `growth_recommendations` | The channel blueprint + ranked recommendations (Phase 7). |
| `reasoned_insights` | Period-over-period shifts with data-backed "why" + the period compared (Phase 8). |

## Generation (Phase 9 — `db/models_generation.py`)
| Table | Purpose |
|---|---|
| `enriched_deals` | Validated deals (merchant-from-URL, price/discount, loot flag, affiliate link). |
| `generated_posts` | Draft posts: rendered text, `format_meta` (incl. emoji policy applied), and **`strategy_rationale`** (why this post follows the strategy — post type, target window, emojis, all with period + sample). |

## Planning (Phase 10 — `db/models_campaign.py`)
| Table | Purpose |
|---|---|
| `sale_events` | India sale calendar (exact vs approximate dates). |
| `campaign_plans` | Daily/weekly/event plans (post allocation, windows, risks, expected outcome). |

## Automation (Phase 11 — `db/models_automation.py`)
| Table | Purpose |
|---|---|
| `scheduled_posts` | **The posting queue.** Each row = one draft → one channel → one fire-time, with status (queued / retry / sending / published / blocked / failed / cancelled), attempts, and last error. This is how posts get published on a schedule; `tgagent automate` processes due rows, and sends stay gated on channel admin rights (blocked rows are recorded honestly, never faked). Shown on the dashboard's **Posting schedule & queue** page. |
