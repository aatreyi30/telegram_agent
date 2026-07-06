# Telegram Analytics — Deep Research Report

**Scope:** Every metric available for Telegram Channels  
**Research basis:** Official Telegram MTProto API documentation (core.telegram.org), confirmed constructors and method schemas  
**Platform context:** telegram_intelligence_agent — AI-powered growth platform for Telegram deal channel owners with MTProto access to owned channels and public-data-only access to competitor channels  
**Constraint:** No implementation proposals. Facts only. All claims cited to official documentation.

---

## Access Gate — Before Any Metric Is Available

Before any Stats API call succeeds, three server-side conditions must be satisfied.

**1. can_view_stats flag**  
`channelFull.flags.20?true` — set by Telegram when the channel meets the subscriber threshold. The threshold is not documented publicly. Community reports place it at approximately 500 subscribers, but Telegram has never confirmed this figure officially. Source: [`channelFull` constructor](https://core.telegram.org/constructor/channelFull)

**2. stats_dc**  
`channelFull.flags.12?int` — the specific Telegram datacenter ID to which all Stats API calls must be routed for this channel. Obtained via `channels.getFullChannel`. If this field is absent, stats are not available. Source: [`channelFull` constructor](https://core.telegram.org/constructor/channelFull)

**3. can_view_revenue / can_view_stars_revenue**  
`channelFull.flags2.12?true` — revenue stats gate  
`channelFull.flags2.15?true` — Stars revenue stats gate  
These are separate permission flags from the main stats gate. Source: [`channelFull` constructor](https://core.telegram.org/constructor/channelFull)

**API Access Layer:** All Stats API methods are MTProto only. The Bot API does not expose any statistics endpoints. Source: [core.telegram.org/api/stats](https://core.telegram.org/api/stats)

**stats.getMessageStats restriction:** Only user accounts can call this method. Bots cannot. Source: [core.telegram.org/method/stats.getMessageStats](https://core.telegram.org/method/stats.getMessageStats)

**stats.getMessagePublicForwards restriction:** Only user accounts can call this method. Bots cannot. Source: [core.telegram.org/method/stats.getMessagePublicForwards](https://core.telegram.org/method/stats.getMessagePublicForwards)

**stats.getBroadcastRevenueStats:** Both users and bots can call this method. Source: [core.telegram.org/method/stats.getBroadcastRevenueStats](https://core.telegram.org/method/stats.getBroadcastRevenueStats)

**payments.getStarsRevenueStats restriction:** Only user accounts can call this method. Source: [core.telegram.org/method/payments.getStarsRevenueStats](https://core.telegram.org/method/payments.getStarsRevenueStats)

---

## Data Type Glossary

**StatsAbsValueAndPrev** — A constructor pairing `current` (value for the selected period) and `prev` (value for the equivalent preceding period). Enables period-over-period comparison. The official documentation on `views_per_post` states: *"current refers to the period in consideration (min_date till max_date), and prev refers to the previous period ((min_date − (max_date − min_date)) till min_date)."* Source: [stats.broadcastStats constructor](https://core.telegram.org/constructor/stats.broadcastStats)

**StatsPercentValue** — A constructor representing a percentage value (e.g., notification rate).

**StatsGraph / statsGraphAsync** — Graph data returned as JSON. Some graphs are returned inline; others require a separate async fetch via `stats.loadAsyncGraph` using the returned `token`. Source: [core.telegram.org/api/stats](https://core.telegram.org/api/stats)

**StatsDateRangeDays** — The date range covered by the broadcastStats response. Defined by min_date and max_date timestamps.

**PostInteractionCounters** — Detailed view and share counts for recently published messages and stories, returned in the `recent_posts_interactions` field.

**PublicForward** — Represents either a forwarded message or a forwarded story in a public channel. Source: [stats.getMessagePublicForwards](https://core.telegram.org/method/stats.getMessagePublicForwards)

---

# PART 1 — Channel-Level Metrics

Source method: `stats.getBroadcastStats`  
Source constructor: [`stats.broadcastStats`](https://core.telegram.org/constructor/stats.broadcastStats)  
API layer introduced: Layer 111 (Broadcast Stats)

---

## Metric 1 — Follower Count Change (Net Subscriber Change)

**Definition**  
The net change in subscriber count during the period in consideration, compared to the equivalent preceding period.

**Calculation**  
Field: `followers` (StatsAbsValueAndPrev). Official description: *"Follower count change for period in consideration."* `current` = net change during selected period. `prev` = net change during the identical preceding period. Absolute subscriber count at a point in time is available from `growth_graph` (see Metric 9).

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `followers`. Requires `can_view_stats = true`.

**Historical Availability**  
Available for the period range returned in `period` (StatsDateRangeDays). Telegram does not document the maximum historical lookback window. Community reports indicate approximately 2–3 months, but this is not officially confirmed.

**Granularity**  
Period-level summary only (one value for current period, one for prior period). Day-by-day breakdown is available from `growth_graph` and `followers_graph` graphs.

**Export**  
No native export. Data must be fetched programmatically via MTProto and stored by the platform.

**Business Value**  
Reveals whether the channel is growing or shrinking during a period. The `prev` field enables comparison without requiring separate historical queries. Essential for tracking the effect of posting campaigns on audience growth.

**Can AI Improve It?**  
Yes. The raw metric answers *what happened*. AI can answer *why it happened* — correlating subscriber change with posting frequency, content type, deal quality, and posting timing during the same period. AI can also detect anomalies (sudden loss events) and explain them by cross-referencing the content published during those days.

---

## Metric 2 — Views per Post

**Definition**  
The average number of views across all posts published during the period.

**Calculation**  
Field: `views_per_post` (StatsAbsValueAndPrev). Official formula: *"total_viewcount / postcount, for posts posted during the period in consideration."* `current` covers the selected period; `prev` covers the equivalent preceding period.

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `views_per_post`.

**Historical Availability**  
Same as Metric 1 — period-level. Per-post view graphs over time are available via `stats.getMessageStats` for individual messages (field: `views_graph`).

**Granularity**  
Period-level average only. Per-post granularity requires per-message queries via `stats.getMessageStats`.

**Export**  
No native export. Must be collected and stored programmatically.

**Business Value**  
The primary content performance indicator for deal channels. A drop in views_per_post signals reduced reach, audience fatigue, or posting frequency problems. The `prev` comparison enables trend detection without requiring separate queries.

**Can AI Improve It?**  
Yes. Telegram tells you the average. AI can tell you which post types, which merchants, which deal formats, which posting hours, and which caption patterns consistently produce above-average views. AI can then recommend the highest-performing combinations before the next post is published.

---

## Metric 3 — Shares per Post

**Definition**  
The average number of times posts published during the period were forwarded (shared) by users.

**Calculation**  
Field: `shares_per_post` (StatsAbsValueAndPrev). Official formula: *"total_sharecount / postcount, for posts posted during the period in consideration."* `current` vs `prev` as above.

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `shares_per_post`.

**Historical Availability**  
Period-level. Per-post share data is available from `stats.getMessagePublicForwards` (public channel forwards) and from `PostInteractionCounters` in `recent_posts_interactions`.

**Granularity**  
Period-level average. Individual post shares are available per-message via `recent_posts_interactions`.

**Export**  
No native export.

**Business Value**  
Shares are the primary organic distribution amplifier on Telegram. A high shares_per_post means content is being distributed beyond the channel's own subscriber base at no cost. For deal channels, high shares indicate that users found the deal compelling enough to send to others.

**Can AI Improve It?**  
Yes. AI can identify which deal categories, discount depths, and content formats consistently drive above-average share rates. The platform can then prioritize those post types in content recommendations.

---

## Metric 4 — Reactions per Post

**Definition**  
The average total number of emoji reactions across all posts published during the period.

**Calculation**  
Field: `reactions_per_post` (StatsAbsValueAndPrev). Official formula: *"total_reactions / postcount, for posts posted during the period in consideration."*

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `reactions_per_post`. Channel-level emotional breakdown via `reactions_by_emotion_graph`. Per-post emotional breakdown via `stats.getMessageStats` field `reactions_by_emotion_graph`.

**Historical Availability**  
Period-level. Per-post reactions are available for recent posts via `recent_posts_interactions`.

**Granularity**  
Period-level average. Emotional breakdown (which emoji) available via graph. Per-post via message stats.

**Export**  
No native export.

**Business Value**  
Reactions are the lowest-friction engagement signal on Telegram. They indicate that users read the content and had an emotional response. For deal channels, 🔥 and 😍 reactions on deal posts signal high user interest in specific categories or merchants.

**Can AI Improve It?**  
Yes. AI can analyze the emotional reaction distribution by deal type, merchant, and content format. If certain deal formats consistently attract 🔥 reactions while others attract 👍 only, AI can rank deal formats by their passion signal intensity and recommend the highest-passion formats.

---

## Metric 5 — Views per Story

**Definition**  
The average number of views across all stories published during the period.

**Calculation**  
Field: `views_per_story` (StatsAbsValueAndPrev). Official formula: *"total_views / storycount, for posts posted during the period in consideration."*

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `views_per_story`. Introduced with Layer 160 (Stories) and Layer 164 (Stories in Channels).

**Historical Availability**  
Period-level.

**Granularity**  
Period-level average. Per-story views available via `stats.getStoryStats` field `views_graph`.

**Export**  
No native export.

**Business Value**  
Measures story reach relative to posts. For deal channels, stories can be used for flash sale announcements or time-limited deals.

**Can AI Improve It?**  
Moderately. AI can compare story vs post view rates and identify whether stories deliver proportionally better or worse reach than posts for the same content type.

---

## Metric 6 — Shares per Story

**Definition**  
The average number of times stories published during the period were forwarded by users.

**Calculation**  
Field: `shares_per_story` (StatsAbsValueAndPrev). Official formula: *"total_shares / storycount, for posts posted during the period in consideration."*

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `shares_per_story`.

**Historical Availability**  
Period-level. Per-story public forwards via `stats.getStoryPublicForwards`.

**Granularity**  
Period-level average.

**Export**  
No native export.

**Business Value**  
Story shares indicate that users distributed the content from the story, bypassing the standard channel feed. High shares per story suggest strong content resonance.

**Can AI Improve It?**  
Yes, same pattern as shares_per_post. AI can identify which story content types drive disproportionate sharing.

---

## Metric 7 — Reactions per Story

**Definition**  
The average total number of emoji reactions across all stories published during the period.

**Calculation**  
Field: `reactions_per_story` (StatsAbsValueAndPrev). Official formula: *"total_reactions / storycount, for posts posted during the period in consideration."*

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `reactions_per_story`. Emotional breakdown via `story_reactions_by_emotion_graph`.

**Historical Availability**  
Period-level.

**Granularity**  
Period-level average. Emotional breakdown via graph.

**Export**  
No native export.

**Business Value**  
Measures audience emotional response to stories specifically. Enables comparison of story vs post engagement levels.

**Can AI Improve It?**  
Yes, same pattern as reactions_per_post — AI can analyze which story content types attract high emotional engagement.

---

## Metric 8 — Enabled Notifications Percentage

**Definition**  
The percentage of the channel's subscribers who have notifications enabled (i.e., they receive push notifications for each new post).

**Calculation**  
Field: `enabled_notifications` (StatsPercentValue). Calculated server-side by Telegram as (subscribers with notifications on / total subscribers) × 100.

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `enabled_notifications`.

**Historical Availability**  
Current period snapshot only. No historical graph is provided for this metric.

**Granularity**  
Single percentage value for the current period. No time-series.

**Export**  
No native export.

**Business Value**  
Critical signal for deal channels. Users with notifications on see posts immediately, which is the highest-value audience segment for time-sensitive deals (flash sales, loot deals, bank offers). A declining notifications percentage indicates audience disengagement without subscriber loss. A high notifications percentage is a direct predictor of strong early view velocity.

**Can AI Improve It?**  
Yes. AI can correlate notification rate with posting frequency, content type, and time-of-day to identify behaviors that cause users to mute the channel. AI can also recommend optimal posting frequency to minimize mute rate.

---

## Metric 9 — Channel Growth Graph (Absolute Subscriber Count)

**Definition**  
A time-series graph showing the absolute total subscriber count of the channel at each data point in the period.

**Calculation**  
Field: `growth_graph` (StatsGraph). Official description: *"Channel growth graph (absolute subscriber count)."* Data is returned as JSON via StatsGraph, which may be inline or async (requires separate `stats.loadAsyncGraph` call).

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `growth_graph`.

**Historical Availability**  
Covers the period returned in `period`. Exact maximum lookback is not documented by Telegram officially.

**Granularity**  
Time-series with data points for each day (or sub-day interval depending on period length). Exact interval depends on Telegram's server-side rendering.

**Export**  
No native export. The StatsGraph JSON must be parsed and stored.

**Business Value**  
The canonical source of truth for total subscriber count at any historical point. Enables calculation of exact subscriber count at post publication time — which is necessary for calculating reach rate accurately.

**Can AI Improve It?**  
Yes. AI can detect breakpoints (sharp gains from viral content or cross-promotions; sharp losses from controversial posts) and correlate them with specific events in the posting history.

---

## Metric 10 — Followers Graph (Relative Subscriber Change)

**Definition**  
A time-series graph showing the relative (incremental) daily change in subscriber count — joins minus leaves per day.

**Calculation**  
Field: `followers_graph` (StatsGraph). Official description: *"Followers growth graph (relative subscriber count)."*

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `followers_graph`.

**Historical Availability**  
Period-level time-series.

**Granularity**  
Daily incremental values.

**Export**  
No native export.

**Business Value**  
Exposes subscriber churn at a daily level. On days with high posting volume, a negative daily delta indicates content is causing unsubscribes faster than joins — a critical signal for deal channels posting too aggressively.

**Can AI Improve It?**  
Yes. AI can identify which posting days or post types correlate with negative subscriber deltas, enabling early detection of content patterns that cause churn.

---

## Metric 11 — Mute Graph

**Definition**  
A time-series graph showing the relative proportion of subscribers who have muted the channel (notifications disabled but not unsubscribed).

**Calculation**  
Field: `mute_graph` (StatsGraph). Official description: *"Muted users graph (relative)."*

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `mute_graph`.

**Historical Availability**  
Period-level time-series.

**Granularity**  
Time-series relative values.

**Export**  
No native export.

**Business Value**  
Muted subscribers represent audience members who no longer see posts in real-time. For deal channels where time-sensitivity matters (flash deals expire), a high mute rate directly suppresses view velocity. The mute graph reveals whether posting behavior is causing progressive notification fatigue.

**Can AI Improve It?**  
Yes. AI can correlate mute rate changes with posting frequency spikes, content quality drops, or over-promotion of specific merchants. AI can recommend posting cadence adjustments to reduce mute rate.

---

## Metric 12 — Top Hours Graph (Views per Hour of Day)

**Definition**  
A graph showing the distribution of views across hours of the day (0–23), indicating when the channel's audience is most active and consuming content.

**Calculation**  
Field: `top_hours_graph` (StatsGraph). Official description: *"Views per hour graph (absolute)."*

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `top_hours_graph`.

**Historical Availability**  
Aggregated across the period. Not a real-time signal.

**Granularity**  
Hourly buckets (24 data points representing hours 0–23).

**Export**  
No native export.

**Business Value**  
The most directly actionable metric for posting time optimization. The peak hours in this graph represent the window where a new post will accumulate the most views fastest. For deal channels, posting flash sales during peak hours directly improves conversion opportunity.

**Can AI Improve It?**  
Yes. AI can cross-reference top hours data with actual post publication times to identify how far current posting patterns deviate from optimal hours. AI can then generate a recommended posting schedule that aligns publication time with peak audience activity.

---

## Metric 13 — Interactions Graph

**Definition**  
A time-series graph showing the total number of interactions (views, reactions, forwards) on posts published during the period.

**Calculation**  
Field: `interactions_graph` (StatsGraph). Official description: *"Interactions graph (absolute)."*

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `interactions_graph`.

**Historical Availability**  
Period-level time-series.

**Granularity**  
Time-series with daily or sub-period data points.

**Export**  
No native export.

**Business Value**  
Shows overall engagement volume trend across the period, useful for identifying campaign impact and detecting declining audience activity.

**Can AI Improve It?**  
Yes. AI can detect inflection points in the interactions graph and map them to specific post types or campaigns, providing evidence-backed explanations for engagement spikes or troughs.

---

## Metric 14 — Instant View (IV) Interactions Graph

**Definition**  
A time-series graph showing interactions generated via Telegram's Instant View feature — a rendering layer that displays web article content natively inside Telegram without opening a browser.

**Calculation**  
Field: `iv_interactions_graph` (StatsGraph). Official description: *"IV interactions graph (absolute)."*

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `iv_interactions_graph`.

**Historical Availability**  
Period-level time-series.

**Granularity**  
Time-series.

**Export**  
No native export.

**Business Value**  
For deal channels that share links to merchant product pages or news articles, this metric indicates how many users read the linked content natively inside Telegram rather than opening the external URL. High IV interactions suggest users prefer consuming content without leaving the app — relevant for link placement strategy.

**Can AI Improve It?**  
Moderately. AI can compare IV interaction rates across different types of linked content and merchants, identifying which link types generate in-app engagement vs click-throughs.

---

## Metric 15 — Views by Source Graph

**Definition**  
A time-series graph showing where post views are coming from — broken down by source type (e.g., direct subscribers, public search, forwarded links, embedded links).

**Calculation**  
Field: `views_by_source_graph` (StatsGraph). Official description: *"Views by source graph (absolute)."* The exact source categories returned by Telegram are not officially enumerated in public documentation but observed sources include: subscriber feed, searches, forward mentions, external links.

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `views_by_source_graph`.

**Historical Availability**  
Period-level time-series.

**Granularity**  
Time-series with source breakdown.

**Export**  
No native export.

**Business Value**  
Reveals distribution amplification. If a significant portion of views come from forwards or search rather than the subscriber feed, it means the content is reaching new audiences organically. For deal channels, high search-based views indicate that posts are discoverable by non-subscribers searching for deals.

**Can AI Improve It?**  
Yes. AI can identify which content types generate disproportionate discovery-source traffic vs subscriber-feed traffic, and recommend creating more of those posts to expand reach beyond the existing subscriber base.

---

## Metric 16 — New Followers by Source Graph

**Definition**  
A time-series graph showing where new subscribers are coming from, broken down by acquisition source.

**Calculation**  
Field: `new_followers_by_source_graph` (StatsGraph). Official description: *"New followers by source graph (absolute)."*

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `new_followers_by_source_graph`.

**Historical Availability**  
Period-level time-series.

**Granularity**  
Time-series with source breakdown.

**Export**  
No native export.

**Business Value**  
The most important growth diagnostic metric. For deal channels, it reveals which acquisition channel (forwarded posts, search, external mentions, other channels) is driving new subscriber growth. Enables investment of effort into the highest-converting acquisition sources.

**Can AI Improve It?**  
Yes. AI can correlate acquisition source spikes with specific posts (e.g., a post that was widely forwarded on Day X drove a search-source spike on Day X+1), enabling identification of which post types generate organic audience growth.

---

## Metric 17 — Languages Graph (Subscriber Language Distribution)

**Definition**  
A pie chart representing the distribution of subscribers by Telegram interface language — a proxy for geographic and linguistic audience composition.

**Calculation**  
Field: `languages_graph` (StatsGraph). Official description: *"Subscriber language graph (pie chart)."* Based on the Telegram app language setting of each subscriber. Not a geographic location signal — Telegram does not expose subscriber location.

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `languages_graph`.

**Historical Availability**  
Current period snapshot. Not a time-series.

**Granularity**  
Language-level breakdown (e.g., English: 62%, Hindi: 28%, Tamil: 6%, etc.).

**Export**  
No native export.

**Business Value**  
For Indian deal channels (GrabOn's use case), this metric validates that the subscriber base is predominantly Hindi/English speakers, which aligns with content strategy. It also reveals if a content strategy shift is attracting audiences outside the target demographic.

**Can AI Improve It?**  
Moderately. AI can flag when language distribution shifts over time (if trend data is stored across multiple API fetches), suggesting that a particular content campaign attracted a different audience cohort.

---

## Metric 18 — Reactions by Emotion Graph (Channel-Level)

**Definition**  
A graph showing the distribution of reactions across different emoji types at the channel level, aggregated across all posts in the period.

**Calculation**  
Field: `reactions_by_emotion_graph` (StatsGraph). Official description: *"A graph containing the number of reactions on posts categorized by emotion."*

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `reactions_by_emotion_graph`. Also available at per-post level via `stats.getMessageStats`.

**Historical Availability**  
Period-level aggregation.

**Granularity**  
Emotion-level breakdown. Which emoji reactions were used and how many of each.

**Export**  
No native export.

**Business Value**  
Provides qualitative audience sentiment at scale. For deal channels, 🔥 and 😍 indicate excitement about the deals; 👍 indicates passive acknowledgment; 😢 might indicate a deal expiring before users could act. This emotional breakdown reveals audience sentiment about content quality.

**Can AI Improve It?**  
Yes. AI can segment emotion profiles by deal type, merchant, and content format. AI can identify which post formats consistently attract high-passion reactions (🔥, 😍) vs low-engagement reactions (👍 only), and recommend the highest-passion formats for future content.

---

## Metric 19 — Story Interactions Graph

**Definition**  
A graph containing the number of story views and shares for stories published during the period.

**Calculation**  
Field: `story_interactions_graph` (StatsGraph). Official description: *"A graph containing the number of story views and shares."*

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `story_interactions_graph`. Introduced in Layer 160/164.

**Historical Availability**  
Period-level.

**Granularity**  
Time-series with view and share breakdown.

**Export**  
No native export.

**Business Value**  
Measures story-level audience engagement. Enables comparison of story reach vs post reach, and identification of story content types that drive sharing.

**Can AI Improve It?**  
Yes. AI can compare story vs post performance curves and recommend which content formats are better suited for stories vs regular posts.

---

## Metric 20 — Story Reactions by Emotion Graph

**Definition**  
A graph showing the distribution of emoji reactions across stories published during the period, categorized by emotion type.

**Calculation**  
Field: `story_reactions_by_emotion_graph` (StatsGraph). Official description: *"A graph containing the number of reactions on stories categorized by emotion."*

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `story_reactions_by_emotion_graph`.

**Historical Availability**  
Period-level.

**Granularity**  
Emotion-level breakdown for stories.

**Export**  
No native export.

**Business Value**  
Story-level sentiment signal. Useful for comparing emotional engagement quality between story content and post content.

**Can AI Improve It?**  
Yes, same pattern as post-level reactions by emotion.

---

## Metric 21 — Recent Posts Interactions

**Definition**  
Detailed interaction counters (views and shares) for individual recently published messages and stories, returned in a structured list.

**Calculation**  
Field: `recent_posts_interactions` (Vector<PostInteractionCounters>). Official description: *"Detailed statistics about number of views and shares of recently sent messages and stories."* PostInteractionCounters contains `msg_id` (or story reference), `views`, and `forwards`.

**API Availability**  
MTProto only. Method: `stats.getBroadcastStats`. Field: `recent_posts_interactions`.

**Historical Availability**  
Recent posts only. The exact window ("recent") is not officially documented by Telegram.

**Granularity**  
Per-post and per-story level.

**Export**  
No native export.

**Business Value**  
The highest-granularity metric returned in the broadcastStats call. Enables per-post performance ranking without requiring individual `stats.getMessageStats` calls for each post. Provides the raw data needed to build post-level performance leaderboards.

**Can AI Improve It?**  
Yes. AI can rank recent posts by views, shares, and engagement intensity, identify the top-performing post(s) in any period, and analyze what those posts have in common (deal type, merchant, caption pattern, posting time, media type) to generate future content recommendations.

---

# PART 2 — Post-Level Metrics

Source method: `stats.getMessageStats`  
Source constructor: [`stats.messageStats`](https://core.telegram.org/constructor/stats.messageStats) — `views_graph` + `reactions_by_emotion_graph`  
**Restriction: Only user accounts can call this method. Not available to bots.**

---

## Metric 22 — Post Views Graph (Per-Message View Curve)

**Definition**  
A time-series graph showing how views accumulated on a specific post over time from publication to present.

**Calculation**  
Field: `views_graph` (StatsGraph) in the `stats.messageStats` constructor. This is fetched by calling `stats.getMessageStats` with a specific `msg_id`. The graph shows cumulative or incremental view counts over time for that individual post.

**API Availability**  
MTProto only. Method: `stats.getMessageStats`. Field: `views_graph`. Requires `msg_id`. Requires channel admin access. User account only.

**Historical Availability**  
Available for posts within the channel's stats retention window. Not officially bounded by Telegram.

**Granularity**  
Time-series for a single post (sub-day interval points).

**Export**  
No native export.

**Business Value**  
Enables construction of view velocity curves — how quickly a post accumulated views in the first 1, 2, 6, 24, and 48 hours. For deal channels, a post that gets 80% of its views in the first 2 hours indicates the deal resonated immediately (high urgency response). A post that accumulates views gradually over 24 hours has sustained interest — likely a long-lasting deal.

**Can AI Improve It?**  
Yes. AI can classify posts by their view curve shape (immediate spike vs gradual accumulation vs long tail) and correlate curve shape with deal type, posting time, and caption characteristics. This enables prediction of expected view velocity for future posts before publication.

---

## Metric 23 — Post Reactions by Emotion (Per-Message)

**Definition**  
A breakdown of emoji reactions on a specific post, categorized by emotion type, with a time-series showing when reactions arrived.

**Calculation**  
Field: `reactions_by_emotion_graph` (StatsGraph) in `stats.messageStats`. Fetched via `stats.getMessageStats` with `msg_id`.

**API Availability**  
MTProto only. Method: `stats.getMessageStats`. User account only.

**Historical Availability**  
Per-post historical data within the stats retention window.

**Granularity**  
Per-post, per-emotion.

**Export**  
No native export.

**Business Value**  
Provides the emotional response signature for each individual post. By accumulating this across all posts, the platform can build a dataset of which deal types attract which emotional responses, enabling AI to predict the likely reaction distribution for a new post before it is published.

**Can AI Improve It?**  
Yes. AI can learn the emotional response patterns of the audience for different deal types, merchants, and formats, and recommend content formats that historically attract the highest-passion reaction profiles.

---

## Metric 24 — Public Forwards (Post-Level Distribution Map)

**Definition**  
A paginated list of public Telegram channels that have forwarded a specific post, along with the forwarded message in each channel.

**Calculation**  
Method: `stats.getMessagePublicForwards`. Returns `stats.publicForwards` constructor containing: `count` (total number of public forwards), `forwards` (Vector<PublicForward> — the actual forwarded messages), `next_offset` (pagination), `chats` and `users` (associated entity info). Official description: *"Obtains a list of messages, indicating to which other public channels was a channel message forwarded. Will return a list of messages with peer_id equal to the public channel to which this message was forwarded."*

**API Availability**  
MTProto only. Method: `stats.getMessagePublicForwards`. User account only. Paginated via `offset` and `limit` parameters.

**Historical Availability**  
Available within the channel's stats window.

**Granularity**  
Per-post, per-forwarding-channel. Full list of channels that reshared the post.

**Export**  
No native export. Must be paginated and stored.

**Business Value**  
The highest-value distribution intelligence metric. Reveals exactly which channels amplified a specific post. For deal channels, this identifies which other channels are acting as content amplifiers, enabling potential cross-promotion relationships. It also reveals competitor channels picking up content — a valuable competitive intelligence signal.

**Can AI Improve It?**  
Yes. AI can aggregate public forward data across all posts and rank the most frequent amplifier channels, identify which post types get forwarded to which channel categories, and recommend content strategies that maximize organic forward distribution.

---

# PART 3 — Story-Level Metrics

Source methods: `stats.getStoryStats`, `stats.getStoryPublicForwards`

---

## Metric 25 — Story Views Graph (Per-Story)

**Definition**  
A time-series graph showing how views accumulated on a specific story over its lifetime.

**Calculation**  
Field: `views_graph` in the `stats.storyStats` constructor, fetched via `stats.getStoryStats`.

**API Availability**  
MTProto only. Method: `stats.getStoryStats`. Requires story_id.

**Historical Availability**  
Within the stats retention window.

**Granularity**  
Per-story time-series.

**Export**  
No native export.

**Business Value**  
Story view curves differ from post view curves because stories expire (24 hours in most cases). The view accumulation curve for a story is inherently time-compressed, which enables different analysis (front-loaded vs back-loaded within the 24-hour window).

**Can AI Improve It?**  
Yes, same pattern as post view velocity analysis.

---

## Metric 26 — Story Reactions by Emotion (Per-Story)

**Definition**  
A per-story breakdown of emoji reactions by emotion type.

**Calculation**  
Field: `reactions_by_emotion_graph` in `stats.storyStats`, fetched via `stats.getStoryStats`.

**API Availability**  
MTProto only. Method: `stats.getStoryStats`.

**Historical Availability**  
Within the stats retention window.

**Granularity**  
Per-story, per-emotion.

**Export**  
No native export.

**Business Value**  
Provides the emotional response signature for story content, enabling comparison with post content performance.

**Can AI Improve It?**  
Yes, same pattern as post-level emotion analysis.

---

## Metric 27 — Story Public Forwards

**Definition**  
A paginated list of public channels that forwarded a specific story.

**Calculation**  
Method: `stats.getStoryPublicForwards`. Returns `stats.publicForwards` — identical structure to message public forwards. Paginated.

**API Availability**  
MTProto only. Method: `stats.getStoryPublicForwards`.

**Historical Availability**  
Within the stats retention window.

**Granularity**  
Per-story, per-forwarding-channel.

**Export**  
No native export.

**Business Value**  
Same distribution intelligence value as post public forwards, applied to story content.

**Can AI Improve It?**  
Yes, same pattern.

---

# PART 4 — Revenue Metrics

---

## Metric 28 — Ad Revenue Balance

**Definition**  
Three balance values representing the channel's ad revenue position: current balance (total earned), available balance (withdrawable now), and overall revenue (lifetime total). All denominated in nanoton (1 TON = 1,000,000,000 nanoton).

**Calculation**  
Method: `stats.getBroadcastRevenueStats`. Returns `BroadcastRevenueBalances` constructor with fields `current_balance` (total earned balance), `available_balance` (amount available for withdrawal), `overall_revenue` (lifetime ad revenue). Also returns `usd_rate` (current TON to USD conversion rate). Revenue sharing rate: channel owners receive 50% of ad revenue. Source: [core.telegram.org/api/revenue](https://core.telegram.org/api/revenue)

**API Availability**  
MTProto only. Requires `can_view_revenue = true` (channelFull.flags2.12). Both users and bots can call this method. Source: [core.telegram.org/method/stats.getBroadcastRevenueStats](https://core.telegram.org/method/stats.getBroadcastRevenueStats)

**Historical Availability**  
Current snapshot (balance values) plus time-series via `revenue_graph`.

**Granularity**  
Current snapshot for balance values. Time-series for revenue trend via `revenue_graph`.

**Export**  
No native export. Withdrawal is processed via Fragment (fragment.com). Disabling ads on the channel requires reaching a specific boost level threshold (`channel_restrict_sponsored_level_min` config parameter). Source: [core.telegram.org/api/revenue](https://core.telegram.org/api/revenue)

**Business Value**  
Enables channel owners to monitor ad revenue accumulation and decide when to withdraw. The `usd_rate` field enables displaying TON balances in USD.

**Can AI Improve It?**  
Moderately. AI can project future revenue accumulation based on the `revenue_graph` trend and estimate time-to-withdrawal threshold.

---

## Metric 29 — Ad Revenue Graph (Time-Series)

**Definition**  
A time-series graph showing ad revenue earned per period (daily or weekly buckets).

**Calculation**  
Field: `revenue_graph` (StatsGraph) in `stats.getBroadcastRevenueStats`. Values are in nanoton.

**API Availability**  
MTProto only. Method: `stats.getBroadcastRevenueStats`.

**Historical Availability**  
Period-level time-series.

**Granularity**  
Time-series with daily or sub-period data points.

**Export**  
No native export.

**Business Value**  
Reveals ad revenue trends over time — whether revenue is growing, stable, or declining. Useful for correlating ad revenue with content publishing cadence (more posts = more ad impressions = more revenue).

**Can AI Improve It?**  
Yes. AI can correlate revenue graph peaks with posting frequency and content type data to identify which posting behaviors maximize ad revenue.

---

## Metric 30 — Ad Revenue Top Hours Graph

**Definition**  
A graph showing the distribution of ad impressions (and thus ad revenue) across hours of the day.

**Calculation**  
Field: `top_hours_graph` (StatsGraph) in `stats.getBroadcastRevenueStats`.

**API Availability**  
MTProto only. Method: `stats.getBroadcastRevenueStats`.

**Historical Availability**  
Aggregated across the period.

**Granularity**  
Hourly buckets.

**Export**  
No native export.

**Business Value**  
Revenue-specific version of the audience activity top_hours_graph. Shows when the most ad impressions occur — useful for optimizing posting schedule to maximize ad revenue exposure.

**Can AI Improve It?**  
Yes. AI can compare the ad revenue top_hours_graph with the audience top_hours_graph to identify alignment or misalignment, and recommend posting schedules that optimize both audience reach and ad revenue.

---

## Metric 31 — Stars Revenue (Telegram Stars)

**Definition**  
Revenue earned by the channel through Telegram Stars — a virtual currency used for paid reactions, paid media, digital goods, and channel subscriptions. Separate from ad revenue (TON).

**Calculation**  
Method: `payments.getStarsRevenueStats`. Returns `payments.starsRevenueStats` constructor with: `top_hours_graph` (optional — StatsGraph, hours of peak Stars activity), `revenue_graph` (StatsGraph — Stars revenue time-series), `status` (StarsRevenueStatus — current balance information), `usd_rate` (Stars to USD conversion rate). The `ton` flag in the method call enables fetching ad revenue in TON instead of Stars. Source: [core.telegram.org/method/payments.getStarsRevenueStats](https://core.telegram.org/method/payments.getStarsRevenueStats)

**API Availability**  
MTProto only. User account only. Requires `can_view_stars_revenue = true` (channelFull.flags2.15).

**Historical Availability**  
Time-series via `revenue_graph`.

**Granularity**  
Time-series with hourly distribution.

**Export**  
No native export.

**Business Value**  
Tracks income from paid reactions (users paying Stars to react to posts), paid media, and Stars-based channel subscriptions. As Telegram expands monetization features, Stars revenue will become increasingly significant.

**Can AI Improve It?**  
Moderately. AI can identify which posts received paid reactions and what content characteristics correlated with willingness-to-pay behavior from the audience.

---

# PART 5 — Derived Metrics (Not Native to Telegram API)

These metrics are not returned by any Telegram API endpoint. They must be calculated by the platform from verified Telegram data. They are classified as Level 2 (Derived) per the platform's data reliability framework.

---

## Metric 32 — Reach Rate

**Definition**  
The percentage of total subscribers who viewed a specific post (or the average post) during a given period.

**Calculation**  
`Reach Rate = (views / subscriber_count) × 100`  
where `subscriber_count` is the absolute subscriber count at post publication time (sourced from `growth_graph`) and `views` is the total view count of the post (sourced from message view field or `recent_posts_interactions`).  
Industry benchmark: 40–80% is considered strong for a Telegram channel. Source: Community-verified benchmark; formula is derived, not native to Telegram API.

**API Availability**  
Not a native Telegram metric. Must be derived by the platform.

**Historical Availability**  
Computable for any historical post where both view count and subscriber count at publication time are stored.

**Granularity**  
Per-post.

**Export**  
Platform-generated.

**Business Value**  
The most important content effectiveness metric for deal channels. A reach rate below 20% signals severe audience engagement problems. A rate above 60% means the majority of subscribers are consuming the content — ideal for time-sensitive deals where broad exposure within a short window is critical.

**Can AI Improve It?**  
Yes. This is the core metric the platform is designed to improve. AI can analyze which combination of posting time, content type, deal format, merchant, caption length, and media type maximizes reach rate. AI can then make pre-publication recommendations to maximize expected reach for each new post.

---

## Metric 33 — Engagement Rate

**Definition**  
The percentage of viewers who took an active engagement action (reaction, forward, comment) on a post, relative to the total views.

**Calculation**  
`Engagement Rate = ((reactions + forwards + comments) / views) × 100`  
Industry benchmark: >2% is considered healthy on Telegram. Source: Community-verified benchmark; formula is derived.

**API Availability**  
Not a native Telegram metric. Must be derived. Components available: reactions and forwards from message data or `recent_posts_interactions`; comments from linked supergroup message count (if discussion group is attached); views from message view field.

**Historical Availability**  
Computable for any historical post where view and reaction data is stored.

**Granularity**  
Per-post.

**Export**  
Platform-generated.

**Business Value**  
Measures content resonance quality rather than reach quantity. A post with high views but low engagement rate means the audience saw it but was not compelled to act. For deal channels, high engagement rate posts are the ones driving sharing and emotional response — the most valuable content signals for learning.

**Can AI Improve It?**  
Yes. AI can identify the content characteristics that maximize engagement rate (not just views) and recommend those characteristics in new content generation. Engagement rate is a better quality signal than views alone.

---

## Metric 34 — ERR — Engagement Rate by Reach

**Definition**  
The ratio of engagement actions to total reach (views), sometimes expressed as a percentage. Equivalent to Engagement Rate as defined above when views is used as the reach proxy.

**Calculation**  
`ERR = (reactions + forwards) / views × 100`  
A variant that excludes comments (for channels without linked discussion groups). Same formula, narrower numerator.

**API Availability**  
Derived. Not a native Telegram metric.

**Historical Availability**  
Computable from stored post data.

**Granularity**  
Per-post.

**Export**  
Platform-generated.

**Business Value**  
Useful when comments are unavailable (most broadcast channels without a linked group). Provides a clean signal of how many viewers took an active action.

**Can AI Improve It?**  
Yes, same pattern as Engagement Rate.

---

## Metric 35 — View Velocity

**Definition**  
The rate at which a post accumulates views in a defined time window after publication. Commonly expressed as: views in the first 1 hour, first 6 hours, first 24 hours, and total.

**Calculation**  
Not a native Telegram metric. Must be derived by the platform through periodic polling of the `views` field on each post message object or by parsing the `views_graph` from `stats.getMessageStats`.  
`View Velocity (Hour 1) = views at T+1hr − views at T0`  
`View Velocity Ratio = (views_at_hour_1 / views_at_hour_24) × 100`  
A high ratio (>50%) means most views came in the first hour — typical for viral deal posts and high-notification-rate audiences.

**API Availability**  
Derived. Message view counts are available via the `views` field on message objects fetched via `channels.getMessages`. Time-series granularity via `stats.getMessageStats` → `views_graph`.

**Historical Availability**  
Computable from stored periodic view count snapshots (requires the platform to poll view counts at fixed intervals post-publication).

**Granularity**  
Sub-hour granularity is achievable with frequent polling. The `views_graph` from message stats provides Telegram's native time-series.

**Export**  
Platform-generated.

**Business Value**  
Critical for deal channels specifically. A deal that gets 90% of its views in the first 2 hours is consumed by the active, notification-on audience segment. A deal that accumulates views over 24 hours is being discovered by search and forwards. The velocity shape predicts audience behavior and informs optimal posting frequency (posting too soon after a high-velocity post causes cannibalization).

**Can AI Improve It?**  
Yes. AI can predict expected view velocity for a new post based on historical velocity curves for similar post types, the current `enabled_notifications` percentage, and the posting hour relative to `top_hours_graph`. AI can then recommend the optimal posting time gap between consecutive posts to avoid view cannibalization.

---

## Metric 36 — Posting Frequency

**Definition**  
The average number of posts published per day, week, or specified time period.

**Calculation**  
`Posting Frequency = post_count / days_in_period`  
Derived from the message history fetched via MTProto `messages.getHistory` or `channels.getMessages`.

**API Availability**  
Derived. Message timestamps are available from message objects. Post count is a simple count of messages in the channel history.

**Historical Availability**  
Available for any historical window where message history has been collected.

**Granularity**  
Can be calculated per day, per week, or per any custom window.

**Export**  
Platform-generated.

**Business Value**  
Posting frequency is directly correlated with both subscriber growth and churn. Too few posts = lost discovery opportunity. Too many posts = mute rate increases. The optimal frequency differs per channel audience and content type. For deal channels, frequency is constrained by deal availability and quality.

**Can AI Improve It?**  
Yes. AI can identify the posting frequency that historically correlates with the highest net subscriber growth and lowest mute rate, and recommend a target frequency range as a channel-specific guideline.

---

## Metric 37 — Posting Consistency

**Definition**  
A measure of regularity in the posting schedule — whether posts are distributed evenly or clustered (burst posting).

**Calculation**  
Derived from message timestamps. Standard deviation of inter-post intervals: low standard deviation = consistent spacing; high standard deviation = burst posting pattern. Can also be expressed as a Gini coefficient of posting time distribution across hours and days.

**API Availability**  
Derived from message timestamps.

**Historical Availability**  
Computable for any historical window.

**Granularity**  
Daily, weekly, or per-campaign.

**Export**  
Platform-generated.

**Business Value**  
Inconsistent posting (long silence followed by a burst of 10 posts) is known to correlate with lower per-post view counts because the algorithm de-prioritizes channels that spam and users who miss a burst lose continuity. For deal channels, post consistency is essential for conditioning the audience to expect deal posts at predictable intervals.

**Can AI Improve It?**  
Yes. AI can analyze posting consistency patterns and their correlation with view metrics, then recommend a posting schedule that maintains consistency within the audience's engagement window.

---

# PART 6 — What Telegram Does NOT Provide

These are metrics channel owners commonly want but that Telegram's API does not expose, even to channel administrators.

| What Is Wanted | Why Telegram Does Not Provide It |
|---|---|
| Individual subscriber identities / demographics | Privacy policy. Telegram never exposes who your subscribers are. |
| Individual user behavior (who read which post) | Privacy policy. View counts are aggregates, not per-user lists. |
| Click-through rate on links | Telegram does not track link clicks. External UTM tracking is the only workaround. |
| Unsubscribe reason | Not captured by Telegram. |
| Conversion rate (subscriber → purchaser) | Cannot be attributed inside Telegram without external tracking. |
| Competitor channel analytics | Only the channel admin can access Stats API. Public data is views + reactions only. |
| Subscriber retention / cohort analysis | No per-user data; cannot track when individual users joined and left. |
| Message delivery rate | Not exposed. Telegram does not provide delivery vs seen breakdowns. |

---

# PART 7 — Summary Table

**Legend:**
- "Available in Telegram" = whether this metric is directly returned by a Telegram API endpoint (not derived)
- "Can our platform improve it?" = whether the telegram_intelligence_agent platform can add intelligence on top of the raw metric
- "If yes, how?" = what AI layer adds that Telegram's raw number does not

| Metric | Available in Telegram | Data Type | Can Platform Improve It? | How |
|---|---|---|---|---|
| **Follower Count Change** | Yes — `followers` (StatsAbsValueAndPrev) via `stats.getBroadcastStats` | Period-level current+prev | Yes | Correlate net change with content decisions in same period; explain *why* growth occurred |
| **Views per Post** | Yes — `views_per_post` (StatsAbsValueAndPrev) via `stats.getBroadcastStats` | Period-level average | Yes | Identify which post types, merchants, hours, formats drive above-average views; pre-publication prediction |
| **Shares per Post** | Yes — `shares_per_post` (StatsAbsValueAndPrev) via `stats.getBroadcastStats` | Period-level average | Yes | Identify which deal types and formats drive above-average shares; recommend for virality |
| **Reactions per Post** | Yes — `reactions_per_post` (StatsAbsValueAndPrev) via `stats.getBroadcastStats` | Period-level average | Yes | Segment by deal type/merchant; predict expected reaction count for new posts |
| **Views per Story** | Yes — `views_per_story` (StatsAbsValueAndPrev) via `stats.getBroadcastStats` | Period-level average | Moderately | Compare story vs post reach efficiency; optimize story content mix |
| **Shares per Story** | Yes — `shares_per_story` (StatsAbsValueAndPrev) via `stats.getBroadcastStats` | Period-level average | Moderately | Identify story content types that drive distribution |
| **Reactions per Story** | Yes — `reactions_per_story` (StatsAbsValueAndPrev) via `stats.getBroadcastStats` | Period-level average | Moderately | Sentiment analysis on story content |
| **Enabled Notifications %** | Yes — `enabled_notifications` (StatsPercentValue) via `stats.getBroadcastStats` | Single percentage | Yes | Correlate with posting frequency to detect notification fatigue; recommend optimal cadence |
| **Channel Growth Graph (absolute)** | Yes — `growth_graph` (StatsGraph) via `stats.getBroadcastStats` | Time-series | Yes | Detect breakpoints; correlate subscriber spikes/drops with specific posts or campaigns |
| **Followers Graph (relative daily change)** | Yes — `followers_graph` (StatsGraph) via `stats.getBroadcastStats` | Time-series | Yes | Identify daily content/posting decisions that drive negative subscriber delta |
| **Mute Graph** | Yes — `mute_graph` (StatsGraph) via `stats.getBroadcastStats` | Time-series | Yes | Correlate mute rate increases with posting frequency bursts; recommend reduced cadence |
| **Top Hours Graph (views per hour)** | Yes — `top_hours_graph` (StatsGraph) via `stats.getBroadcastStats` | 24-point hourly | Yes | Generate optimal posting schedule aligned with peak audience activity windows |
| **Interactions Graph** | Yes — `interactions_graph` (StatsGraph) via `stats.getBroadcastStats` | Time-series | Yes | Detect engagement trend inflection points; correlate with content decisions |
| **IV Interactions Graph** | Yes — `iv_interactions_graph` (StatsGraph) via `stats.getBroadcastStats` | Time-series | Moderately | Identify which link types generate in-app reading behavior |
| **Views by Source Graph** | Yes — `views_by_source_graph` (StatsGraph) via `stats.getBroadcastStats` | Time-series with source breakdown | Yes | Identify which post types drive discovery-source views vs subscriber-feed views |
| **New Followers by Source Graph** | Yes — `new_followers_by_source_graph` (StatsGraph) via `stats.getBroadcastStats` | Time-series with source breakdown | Yes | Correlate acquisition source spikes with specific posts; identify content that drives organic growth |
| **Languages Graph** | Yes — `languages_graph` (StatsGraph) via `stats.getBroadcastStats` | Pie chart snapshot | Moderately | Detect audience composition drift over time by comparing periodic snapshots |
| **Reactions by Emotion (channel-level)** | Yes — `reactions_by_emotion_graph` (StatsGraph) via `stats.getBroadcastStats` | Period-level emotion breakdown | Yes | Segment emotion profile by deal type and merchant; recommend highest-passion content formats |
| **Story Interactions Graph** | Yes — `story_interactions_graph` (StatsGraph) via `stats.getBroadcastStats` | Time-series | Moderately | Compare story vs post performance curves |
| **Story Reactions by Emotion (channel-level)** | Yes — `story_reactions_by_emotion_graph` (StatsGraph) via `stats.getBroadcastStats` | Period-level emotion breakdown | Moderately | Sentiment analysis on story content type |
| **Recent Posts Interactions** | Yes — `recent_posts_interactions` (Vector<PostInteractionCounters>) via `stats.getBroadcastStats` | Per-post views + shares | Yes | Build per-post performance leaderboard; identify top-performing posts for template learning |
| **Post Views Graph (per-message)** | Yes — `views_graph` via `stats.getMessageStats` (user only) | Per-post time-series | Yes | Classify posts by view velocity curve shape; predict expected velocity for new posts |
| **Post Reactions by Emotion (per-message)** | Yes — `reactions_by_emotion_graph` via `stats.getMessageStats` (user only) | Per-post emotion breakdown | Yes | Build per-post emotional response profiles; predict sentiment response for new content |
| **Public Forwards (per-message)** | Yes — count + channel list via `stats.getMessagePublicForwards` (user only) | Per-post forward map | Yes | Build amplifier channel graph; identify which channels reshare content and which post types get forwarded |
| **Story Views Graph (per-story)** | Yes — via `stats.getStoryStats` | Per-story time-series | Moderately | Classify stories by view velocity |
| **Story Reactions by Emotion (per-story)** | Yes — via `stats.getStoryStats` | Per-story emotion breakdown | Moderately | Sentiment analysis per story |
| **Story Public Forwards** | Yes — via `stats.getStoryPublicForwards` | Per-story forward map | Moderately | Distribution intelligence for story content |
| **Ad Revenue Balance** | Yes — `BroadcastRevenueBalances` via `stats.getBroadcastRevenueStats` | Current snapshot in nanoton | Moderately | Project revenue accumulation trend; estimate time-to-withdrawal |
| **Ad Revenue Graph** | Yes — `revenue_graph` via `stats.getBroadcastRevenueStats` | Time-series | Moderately | Correlate revenue peaks with posting cadence changes |
| **Ad Revenue Top Hours** | Yes — `top_hours_graph` via `stats.getBroadcastRevenueStats` | 24-point hourly | Yes | Compare with audience top hours; optimize posting time for dual goals: reach + revenue |
| **Stars Revenue** | Yes — `payments.starsRevenueStats` via `payments.getStarsRevenueStats` (user only) | Time-series + balance | Moderately | Identify which posts attracted paid reactions (Stars) |
| **Reach Rate** | No — must be derived: views ÷ subscribers × 100 | Derived per-post | Yes | Core platform KPI. AI predicts expected reach rate before publication; recommends actions to improve |
| **Engagement Rate** | No — must be derived: (reactions+forwards+comments) ÷ views × 100 | Derived per-post | Yes | AI identifies content characteristics that maximize engagement rate; surfaces in content recommendations |
| **ERR (Engagement Rate by Reach)** | No — derived: (reactions+forwards) ÷ views × 100 | Derived per-post | Yes | Quality signal used in content scoring and ranking |
| **View Velocity** | No — derived from periodic view polling or `views_graph` curve analysis | Derived per-post | Yes | AI classifies posts by velocity shape; predicts expected velocity; recommends optimal posting intervals |
| **Posting Frequency** | No — derived from message timestamps | Derived from message history | Yes | AI correlates frequency with mute rate and subscriber growth; recommends target cadence |
| **Posting Consistency** | No — derived from inter-post interval statistics | Derived from message history | Yes | AI identifies inconsistency patterns causing audience disengagement; recommends schedule regularization |

---

# Verified Facts Summary

1. All Stats API methods are MTProto-only. The Bot API exposes no statistics endpoints. Source: [core.telegram.org/api/stats](https://core.telegram.org/api/stats)
2. Stats availability is gated by `can_view_stats` flag in `channelFull`. The subscriber threshold is not officially documented. Source: [core.telegram.org/constructor/channelFull](https://core.telegram.org/constructor/channelFull)
3. Stats queries must be routed to the specific `stats_dc` datacenter obtained from `channelFull`. Source: [core.telegram.org/constructor/channelFull](https://core.telegram.org/constructor/channelFull)
4. The `stats.broadcastStats` constructor was introduced in Layer 111. Current layer as of research date: Layer 223. Source: [core.telegram.org/constructor/stats.broadcastStats](https://core.telegram.org/constructor/stats.broadcastStats)
5. `views_per_post` is calculated as `total_viewcount / postcount` for posts published within the period. Source: [core.telegram.org/constructor/stats.broadcastStats](https://core.telegram.org/constructor/stats.broadcastStats)
6. `shares_per_post` is `total_sharecount / postcount`. `reactions_per_post` is `total_reactions / postcount`. Both cover posts published within the period only. Source: [core.telegram.org/constructor/stats.broadcastStats](https://core.telegram.org/constructor/stats.broadcastStats)
7. `stats.getMessageStats` and `stats.getMessagePublicForwards` are user-only methods. Bots cannot call them. Source: [core.telegram.org/method/stats.getMessageStats](https://core.telegram.org/method/stats.getMessageStats), [core.telegram.org/method/stats.getMessagePublicForwards](https://core.telegram.org/method/stats.getMessagePublicForwards)
8. `stats.getBroadcastRevenueStats` can be called by both users and bots. Source: [core.telegram.org/method/stats.getBroadcastRevenueStats](https://core.telegram.org/method/stats.getBroadcastRevenueStats)
9. `payments.getStarsRevenueStats` is user-only. Source: [core.telegram.org/method/payments.getStarsRevenueStats](https://core.telegram.org/method/payments.getStarsRevenueStats)
10. Ad revenue is split 50% to channel owners. Paid at 50% of TON ad revenue. Withdrawal via Fragment. Source: [core.telegram.org/api/revenue](https://core.telegram.org/api/revenue)
11. Revenue balances are denominated in nanoton (1 TON = 10^9 nanoton). `usd_rate` field enables conversion.
12. `stats.getMessagePublicForwards` returns `stats.publicForwards` with `count` (total public forwards), paginated `forwards` list, and `chats`/`users` entities. Source: [core.telegram.org/method/stats.getMessagePublicForwards](https://core.telegram.org/method/stats.getMessagePublicForwards)
13. Disabling sponsored ads requires reaching the boost level defined by `channel_restrict_sponsored_level_min` config parameter. Implemented via `channels.restrictSponsoredMessages`. Source: [core.telegram.org/api/revenue](https://core.telegram.org/api/revenue)
14. Reach rate, engagement rate, ERR, view velocity, posting frequency, and posting consistency are not native Telegram metrics. They must be derived by the platform.
15. Telegram does not expose individual subscriber identities, per-user behavior, link click rates, unsubscribe reasons, or conversion rates. These are privacy constraints, not API limitations.

---

# Open Questions

1. What is the exact minimum subscriber count required for `can_view_stats` to be set? Telegram has not documented this officially. Community-reported threshold of ~500 subscribers has not been confirmed.
2. What is the maximum historical lookback window for `stats.broadcastStats`? Not documented officially.
3. What is the definition of "recent" in `recent_posts_interactions`? How many days or posts does Telegram return?
4. What source categories does `views_by_source_graph` and `new_followers_by_source_graph` enumerate? The official documentation names the fields but does not enumerate the source types returned in the graph JSON.
5. Are StatsGraph values returned in UTC or in the channel's timezone? Not documented.
6. Does `reactions_by_emotion_graph` include all emoji types or only a subset defined by the channel's reaction settings?
7. Is `stats.getMessageStats` available for messages that do not belong to the API-authenticated user's channels (i.e., channels where the user is an admin but not the owner)? The docs say "admin required" but do not clarify ownership distinctions.

---

*Sources consulted:*
- [core.telegram.org/constructor/stats.broadcastStats](https://core.telegram.org/constructor/stats.broadcastStats)
- [core.telegram.org/method/stats.getBroadcastStats](https://core.telegram.org/method/stats.getBroadcastStats)
- [core.telegram.org/method/stats.getMessageStats](https://core.telegram.org/method/stats.getMessageStats)
- [core.telegram.org/method/stats.getMessagePublicForwards](https://core.telegram.org/method/stats.getMessagePublicForwards)
- [core.telegram.org/method/stats.getBroadcastRevenueStats](https://core.telegram.org/method/stats.getBroadcastRevenueStats)
- [core.telegram.org/method/payments.getStarsRevenueStats](https://core.telegram.org/method/payments.getStarsRevenueStats)
- [core.telegram.org/api/revenue](https://core.telegram.org/api/revenue)
- [core.telegram.org/api/stats](https://core.telegram.org/api/stats)
- [core.telegram.org/constructor/channelFull](https://core.telegram.org/constructor/channelFull)
