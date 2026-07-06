# Telegram Platform — Deep Technical Research Report

**Role:** Senior Technical Researcher
**Date:** July 3, 2026
**Method:** Multi-source fan-out search + adversarial claim verification
**Primary Sources:** core.telegram.org (official Telegram API documentation)

---

## Overview of Telegram's API Surface

Telegram exposes three distinct developer surfaces:

| Surface | Protocol | Use Case |
|---|---|---|
| **Bot API** | HTTP/REST (wrapper over TDLib) | Build bots without MTProto knowledge |
| **MTProto API (TDLib / direct)** | Binary MTProto over TCP/UDP | Build full Telegram clients, access all features |
| **TDLib** | C library (wraps MTProto) | Cross-language Telegram client library |

---

---

# PART 1: VERIFIED FACTS

---

## 1. Telegram Bot API

**Source:** [https://core.telegram.org/bots/api](https://core.telegram.org/bots/api) · [https://core.telegram.org/bots/faq](https://core.telegram.org/bots/faq) · [https://core.telegram.org/bots/features](https://core.telegram.org/bots/features)

### What it is

The Bot API is an HTTP endpoint operated by Telegram that translates developer HTTP requests into MTProto calls via an internal TDLib instance. Developers interact with it via JSON over HTTPS — no knowledge of MTProto required. All bots are created and configured via `@BotFather` on Telegram.

### Message Delivery (Getting Updates)

Two supported modes:

- **Long Polling** (`getUpdates`): Developer polls the Bot API server. The earliest 100 unconfirmed updates are returned. Updates are confirmed by passing `offset = last_update_id + 1`. Cannot be used simultaneously with webhooks.
- **Webhooks** (`setWebhook`): Telegram pushes updates to a developer-supplied HTTPS URL. Supported ports: **443, 80, 88, 8443**. Requires a valid SSL certificate. Wildcard certificates may not be supported. Redirects are not supported. Self-signed certificates are supported if the public key is uploaded via the `certificate` parameter.

**Webhook verification:** No cryptographic signature scheme. The recommended practice is to embed the bot token as a secret path segment in the webhook URL.

### Rate Limits

All limits are subject to change; follow `@BotNews`.

| Scope | Limit |
|---|---|
| Single chat | Max 1 message/second (short bursts allowed; 429 errors follow) |
| Group chats | Max 20 messages/minute |
| Global broadcast (default) | ~30 messages/second |
| Global broadcast (Paid Broadcasts) | Up to 1,000 messages/second |

**Paid Broadcasts (enabled via `@BotFather`):**
- Requires bot to have ≥ **100,000 Telegram Stars** balance.
- Requires ≥ **100,000 monthly active users**.
- Each message beyond the free 30/sec threshold costs **0.1 Stars per message**.
- Only charged for successfully delivered messages.

*Source: [https://core.telegram.org/bots/faq#how-can-i-message-all-of-my-bot-39s-subscribers-at-once](https://core.telegram.org/bots/faq#how-can-i-message-all-of-my-bot-39s-subscribers-at-once)*

### File Handling

| Operation | Limit |
|---|---|
| Upload (send) | Up to **50 MB** per file |
| Download via `getFile` | Only files **up to 20 MB** |
| `file_id` persistence | Yes — `file_id` values are permanent and can be reused |
| File types | Any type |

**Workaround for >20MB downloads:** Use the self-hosted Bot API server or switch to MTProto/TDLib, which supports files up to 2 GB (Premium: 4 GB).

### Message Visibility Rules

1. **All bots** always receive: all service messages, all private chat messages, all messages in channels where they are a member.
2. **Bot admins + privacy-disabled bots:** receive all messages except those from other bots.
3. **Privacy-mode bots (default):** only receive commands addressed to them, general `/start`-type commands if they were last to message the group, messages sent via them (inline), and replies to their messages.
4. **Bots never see messages from other bots** — regardless of mode. This is by design to prevent infinite loops.

### Supported Features

- **Text messages, photos, videos, audio, documents, stickers, animations, voice, video notes, polls, dice, venues, contacts, game scores, live locations.**
- **Keyboards:** `InlineKeyboardMarkup` (buttons with callbacks/URLs/switch_inline), `ReplyKeyboardMarkup` (persistent keyboard), `ReplyKeyboardRemove`, `ForceReply`.
- **Inline Mode:** Bots can respond to `@botname query` in any chat. Supports articles, photos, GIFs, MPEG4 GIFs, videos, audio, voices, documents, locations, venues, contacts, game scores, stickers, cached media. Requires `inline_mode` enabled via `@BotFather`.
- **Deep Linking:** `t.me/botname?start=PAYLOAD` — passes a payload to the bot's `/start` command.
- **Chat and User Selection:** Bots can request the user to select a chat or user to share with the bot.
- **Commands:** Bots can register command lists via `setMyCommands`. Scoped to specific chats, languages, or user types.
- **Payments (Stars & Fiat):** `sendInvoice`, `answerShippingQuery`, `answerPreCheckoutQuery`. As of 2024, Telegram Stars are the primary in-app currency for digital goods.
- **Games:** `sendGame`, `setGameScore`, `getGameHighScores`. Requires game set up via `@BotFather`.
- **Mini Apps (WebApps):** Full JS web apps inside the Telegram client. Launched from inline keyboard buttons, keyboard buttons, or direct links.
- **Sticker Sets:** Bots can create, upload to, and delete sticker sets via `createNewStickerSet`, `addStickerToSet`, `deleteStickerFromSet`.
- **Scheduled Messages:** Bots can send messages with a `schedule_date` parameter.
- **Pins:** Bots with admin rights can pin/unpin messages.
- **Polls/Quizzes:** `sendPoll` supports regular polls and quiz mode. Results obtainable via `getPollAnswer` updates.
- **Media Groups:** `sendMediaGroup` sends albums of up to 10 photos/videos.
- **Reactions:** `setMessageReaction` — available since Bot API 7.x.
- **Bot Admin Actions:** With appropriate admin rights, bots can ban/unban/restrict members, promote/demote admins, pin messages, delete messages, change chat info (title, photo, description), manage invite links, create topics in forum groups.
- **Secretary Bots & Managed Bots:** Bots can manage other bots in a limited fashion (Managed Bots feature).
- **Bot-to-Bot Communication:** Limited — bots cannot see each other's messages, but can communicate via shared databases or through user interactions.

### Required Permissions

Most Bot API admin actions require the bot to be an **administrator** in the chat with the specific `ChatAdminRights` flag set:
- `can_delete_messages`, `can_restrict_members`, `can_promote_members`, `can_change_info`, `can_invite_users`, `can_post_messages` (channels), `can_edit_messages` (channels), `can_pin_messages`, `can_manage_topics`, `can_post_stories`, `can_delete_stories`, `can_edit_stories`, `can_manage_video_chats`, `is_anonymous`, `can_manage_chat`.

### Historical Availability

- Bot API launched: **June 24, 2015** (Telegram Blog).
- Inline mode added: **September 2015**.
- Payments API added: **May 2017**.
- Games API added: **October 2016**.
- Webhooks supported since launch.
- Mini Apps: introduced **April 2022**.
- Paid Broadcasts: introduced **October 31, 2024** (Bot API changelog).

### Official Documentation

- API Reference: [https://core.telegram.org/bots/api](https://core.telegram.org/bots/api)
- Features: [https://core.telegram.org/bots/features](https://core.telegram.org/bots/features)
- FAQ: [https://core.telegram.org/bots/faq](https://core.telegram.org/bots/faq)
- Payments: [https://core.telegram.org/bots/payments](https://core.telegram.org/bots/payments)
- Webhook Guide: [https://core.telegram.org/bots/webhooks](https://core.telegram.org/bots/webhooks)
- Changelog: [https://core.telegram.org/bots/api-changelog](https://core.telegram.org/bots/api-changelog)

---

## 2. Telegram MTProto API

**Source:** [https://core.telegram.org/mtproto](https://core.telegram.org/mtproto) · [https://core.telegram.org/api](https://core.telegram.org/api)

### What it is

MTProto (Mobile Protocol) is Telegram's custom binary protocol for client-server communication. It uses a combination of symmetric (AES-256) and asymmetric (RSA-2048) encryption. Unlike the Bot API, MTProto clients connect directly to Telegram's servers over TCP, UDP, or HTTP (but not standard HTTPS REST). There is no polling or webhook abstraction; the connection is persistent and updates stream in real time.

To use the MTProto API directly, developers must:
1. Obtain `api_id` and `api_hash` from [https://my.telegram.org](https://my.telegram.org).
2. Implement the full MTProto handshake (key exchange, auth key generation, session management).
3. Or use a library like **TDLib**, **Telethon** (Python), **GramJS** (JS), **Pyrogram** (Python), **gotd/td** (Go), **mtcute** (TypeScript).

### Authentication

- **User accounts:** Full phone number + OTP (SMS/call/app code) + optional 2FA password flow. Supports email-based code delivery. Uses `authorizationState` steps (in TDLib) or direct `auth.*` methods.
- **Bot tokens:** Provide the bot token from `@BotFather` instead of phone flow. Still requires `api_id` and `api_hash`.

### Capabilities vs. Bot API

The MTProto API exposes the **full Telegram feature set**. Key capabilities unavailable in Bot API:

| Feature | Bot API | MTProto API |
|---|---|---|
| Read messages as a user | No | Yes |
| Access message history | Limited | Full |
| Manage Business Account settings | No | Yes |
| Access Channel Statistics (JSON) | No | Yes |
| Upload files > 50MB | No (via self-hosted Bot API) | Yes (up to 2GB / 4GB Premium) |
| Secret chats (E2E) | No | Yes |
| Create/join channels or groups | No | Yes |
| Manage Telegram account settings | No | Yes |
| Access Telegram Passport data | No | Yes |
| Read all messages in group (user mode) | No | Yes |
| Access full MTProto schema | No | Yes |

### Rate Limits (MTProto)

Not publicly documented as fixed numbers. Limits are enforced server-side, and violations result in `FLOOD_WAIT_X` errors (X = seconds to wait). Rates differ by method, account type, and server load. Aggressive flooding can result in temporary or permanent account bans.

### Historical Availability

- MTProto Protocol documented publicly since 2013.
- The full API schema: [https://core.telegram.org/schema](https://core.telegram.org/schema)
- Layer version is updated with each API revision; clients must declare their supported layer.

### Official Documentation

- Protocol: [https://core.telegram.org/mtproto](https://core.telegram.org/mtproto)
- API Index: [https://core.telegram.org/api](https://core.telegram.org/api)
- TL Schema: [https://core.telegram.org/schema](https://core.telegram.org/schema)

---

## 3. TDLib (Telegram Database Library)

**Source:** [https://core.telegram.org/tdlib](https://core.telegram.org/tdlib) · [https://core.telegram.org/tdlib/getting-started](https://core.telegram.org/tdlib/getting-started) · [https://github.com/tdlib/td](https://github.com/tdlib/td)

### What it is

TDLib is an open-source, cross-platform library that implements the full Telegram client protocol (MTProto), handles local storage, encryption, network management, and data consistency. It is the foundation on which the official Telegram Bot API server is built. In production, one TDLib instance handles **more than 24,000 active bots simultaneously**.

### Language Support

TDLib exposes itself as a **C dynamic library**. Any language that can call C functions can use TDLib:

- **Native bindings (official):** Java (via JNI), C# (via C++/CLI).
- **JSON interface:** `td_send` / `td_receive` C functions with JSON payloads — usable from any language.
- **Third-party bindings exist for:** Python, Node.js, Go, Ruby, PHP, Swift, Kotlin, Dart, Rust, and more.
- NuGet package: `TDLib` (version 1.8.64.1 as of last check).

### Architecture

- Fully **asynchronous**: requests via `ClientManager.send`, responses via `ClientManager.receive`. Requests never block each other.
- Driven by **updates** pushed from TDLib to the application (e.g., `updateNewMessage`, `updateAuthorizationState`, `updateFile`).
- Manages 4 chat types: private chats, basic groups (0–200 members), supergroups/channels (up to 200,000 members for supergroups; unlimited for channels/broadcast groups), secret chats (E2E, device-local).
- Handles 6 member statuses: Creator, Administrator, Member, Restricted, Left, Banned.
- Supports 45+ message content types (`messageText`, `messagePhoto`, `messageScreenshotTaken`, etc.).
- Manages 3 chat lists: Main, Archive, Folder.

### Initialization Requirements

- Must provide: `api_id`, `api_hash` (from `my.telegram.org`), `database_directory` (writable), `system_language_code`, `device_model`.
- Optional: `use_message_database` (local cache), `use_secret_chats`.

### Licensing

**Boost Software License** — permissive open-source license. Allows commercial and private use without copyleft obligations.

### Backward Compatibility

TDLib's JSON interface follows **semantic versioning**. Same major version = binary and backward compatible. Different minor/patch versions may have different underlying APIs.

### Limitations

- Requires compilation from source (C++). Build is memory-intensive.
- Some languages require wrapper layers to handle the async C callback model.
- No pre-built binaries officially distributed (community packages exist).

### Official Documentation

- TDLib Overview: [https://core.telegram.org/tdlib](https://core.telegram.org/tdlib)
- Getting Started: [https://core.telegram.org/tdlib/getting-started](https://core.telegram.org/tdlib/getting-started)
- API Method Reference: [https://core.telegram.org/tdlib/docs/classtd_1_1td__api_1_1_function.html](https://core.telegram.org/tdlib/docs/classtd_1_1td__api_1_1_function.html)
- TL Schema: [https://github.com/tdlib/td/blob/master/td/generate/scheme/td_api.tl](https://github.com/tdlib/td/blob/master/td/generate/scheme/td_api.tl)
- GitHub: [https://github.com/tdlib/td](https://github.com/tdlib/td)

---

## 4. Channel Administration via API

**Source:** [https://core.telegram.org/api/rights](https://core.telegram.org/api/rights) · [https://core.telegram.org/constructor/chatAdminRights](https://core.telegram.org/constructor/chatAdminRights)

### What Can Be Managed Programmatically

All channel/group administration is available via **MTProto API** (and Bot API for bots that are admins). The following operations are supported:

**Admin Rights Management:**
- `channels.editAdmin` — modify admin rights of a user in a channel or supergroup, using the `chatAdminRights` constructor.
- `messages.editChatAdmin` — for basic groups (no granular rights, binary admin toggle only).
- Admin rights flags: `change_info`, `post_messages`, `edit_messages`, `delete_messages`, `ban_users`, `invite_users`, `pin_messages`, `add_admins`, `anonymous`, `manage_call`, `other`, `manage_topics`, `post_stories`, `edit_stories`, `delete_stories`.

**Banned / Restricted Rights:**
- `channels.editBanned` — ban/kick/restrict a user in a channel or supergroup. Uses `chatBannedRights`.
- `messages.deleteChatUser` — remove a user from a basic group (no granular restrictions available in basic groups for individual users).

**Default (Global) Permissions:**
- `messages.editChatDefaultBannedRights` — set default permissions for all users in a channel, supergroup, or basic group. All `chatBannedRights` flags apply except `view_messages`.

**Bot Admin Right Suggestions:**
- `bots.setBotBroadcastDefaultAdminRights` — bots suggest default rights for when they are added to channels.
- `bots.setBotGroupDefaultAdminRights` — bots suggest default rights for when they are added to groups.
- These suggested rights are overridden by rights in deep links (`t.me/botname?startchannel=...`).

**Other Admin Operations:**
- Pin/unpin messages, change channel title/photo/description, manage invite links, delete messages, restrict slow mode, enable/disable anti-spam, enable/disable join requests, manage forum topics, manage stories posting rights.

### Required Permissions

- User must be a **channel administrator** with `can_promote_members` right to grant/modify admin rights.
- Bots must have appropriate admin rights in the chat to perform admin operations.

### Limitations

- **Basic groups** do not support granular admin rights — only binary admin on/off.
- A bot **cannot promote itself** — it can only grant rights up to the rights it itself has.
- Admins cannot grant themselves rights they don't already possess.

### Official Documentation

- Admin/banned rights: [https://core.telegram.org/api/rights](https://core.telegram.org/api/rights)
- `chatAdminRights` constructor: [https://core.telegram.org/constructor/chatAdminRights](https://core.telegram.org/constructor/chatAdminRights)
- `channels.editAdmin`: [https://core.telegram.org/method/channels.editAdmin](https://core.telegram.org/method/channels.editAdmin)

---

## 5. Telegram Statistics API

**Source:** [https://core.telegram.org/api/stats](https://core.telegram.org/api/stats) · [https://core.telegram.org/method/stats.getBroadcastStats](https://core.telegram.org/method/stats.getBroadcastStats)

### API Surface

The Statistics API is **MTProto-only** — it is **not exposed through the Bot API**. The Bot API's `getChatStatisticsURL` method (if present) returns a URL to a PNG graph image, not JSON data. For programmatic, structured data access, MTProto is required.

### Access Requirements

- User must be a channel/group **administrator**.
- The `channelFull.can_view_stats` flag must be `true` (server-side size threshold; the exact minimum is not publicly documented and is a server-side configuration).
- Requests must be routed to the **specific datacenter** identified by `channelFull.stats_dc` (obtainable via `channels.getFullChannel`).

### Channel Statistics (`stats.getBroadcastStats`)

**API Method:** `stats.getBroadcastStats#ab42441a`
**Returns:** `stats.broadcastStats`

Available metrics:

| Metric | Type | Description |
|---|---|---|
| `period` | `StatsDateRangeDays` | Date range covered |
| `followers` | `StatsAbsValueAndPrev` | Absolute follower count (current vs. prev period) |
| `views_per_post` | `StatsAbsValueAndPrev` | Avg views per post (current vs. prev period) |
| `shares_per_post` | `StatsAbsValueAndPrev` | Avg shares per post |
| `reactions_per_post` | `StatsAbsValueAndPrev` | Avg reactions per post |
| `views_per_story` | `StatsAbsValueAndPrev` | Avg views per story |
| `shares_per_story` | `StatsAbsValueAndPrev` | Avg shares per story |
| `reactions_per_story` | `StatsAbsValueAndPrev` | Avg reactions per story |
| `enabled_notifications` | `StatsPercentValue` | % subscribers with notifications enabled |
| `growth_graph` | `StatsGraph` | Follower growth over time |
| `followers_graph` | `StatsGraph` | Follower count graph |
| `mute_graph` | `StatsGraph` | Mutes over time |
| `top_hours_graph` | `StatsGraph` | Activity by hour of day |
| `interactions_graph` | `StatsGraph` | Interactions over time |
| `iv_interactions_graph` | `StatsGraph` | Instant View interactions |
| `views_by_source_graph` | `StatsGraph` | Views by traffic source |
| `new_followers_by_source_graph` | `StatsGraph` | New followers by source |
| `languages_graph` | `StatsGraph` | Audience language distribution |
| `reactions_by_emotion_graph` | `StatsGraph` | Reactions by emoji type |
| `story_interactions_graph` | `StatsGraph` | Story interactions |
| `story_reactions_by_emotion_graph` | `StatsGraph` | Story reactions by emoji |
| `recent_posts_interactions` | `Vector<PostInteractionCounters>` | Per-post: views, forwards, reactions |

### Supergroup Statistics (`stats.getMegagroupStats`)

**API Method:** `stats.getMegagroupStats#dcdf8607`
**Returns:** `stats.megagroupStats`

Metrics include: `members`, `messages`, `viewers`, `posters`, growth/members/new-members-by-source/languages/messages/actions/top-hours/weekdays graphs, `top_posters` (user, message count, avg chars), `top_admins` (deleted/kicked/banned counts), `top_inviters` (invitation counts).

### Per-Message Statistics (`stats.getMessageStats`)

**API Method:** `stats.getMessageStats#b6e0a3f5`
**Returns:** `stats.messageStats`

- `views_graph` — view count over time for a specific message.
- `reactions_by_emotion_graph` — reactions by type for that message.

Also: `stats.getMessagePublicForwards` — lists public channels that forwarded a specific message, with pagination.

### Per-Story Statistics (`stats.getStoryStats`, `stats.getStoryPublicForwards`)

- `views_graph`, `reactions_by_emotion_graph` for a specific story.
- List of public channels that forwarded or reposted a story.

### Graph Data Format

- Graphs delivered as JSON inside a `DataJSON` field.
- Some graphs are returned as `statsGraphAsync` (with a `token`) — these must be fetched separately via `stats.loadAsyncGraph` to reduce server load.
- Graphs support zooming via `zoom_token` — call `stats.loadAsyncGraph` with the `x` coordinate of a data point to get a drilled-down subgraph.
- 4 graph visualization types: line, step, bar, area. Percentage area graphs zoom to pie charts.

### Refresh Frequency

- The `period` field indicates the time range. The documentation states "the period typically depends on channel activity" — there is no published fixed refresh interval. Data appears to update approximately daily based on community reports, but this is not confirmed in official documentation.

### Export Support

- Data is returned as **JSON** in the `statsGraph.json` field (a `DataJSON` constructor with a `data` string containing the raw JSON).
- No official bulk export or CSV endpoint. Raw JSON must be parsed by the client.
- The Telegram Desktop app's "Export Chat History" feature exports messages as JSON, but does not export analytics statistics.

### Official Documentation

- [https://core.telegram.org/api/stats](https://core.telegram.org/api/stats)
- `stats.getBroadcastStats`: [https://core.telegram.org/method/stats.getBroadcastStats](https://core.telegram.org/method/stats.getBroadcastStats)
- `stats.getMegagroupStats`: [https://core.telegram.org/method/stats.getMegagroupStats](https://core.telegram.org/method/stats.getMegagroupStats)
- `stats.getMessageStats`: [https://core.telegram.org/method/stats.getMessageStats](https://core.telegram.org/method/stats.getMessageStats)
- `stats.getMessagePublicForwards`: [https://core.telegram.org/method/stats.getMessagePublicForwards](https://core.telegram.org/method/stats.getMessagePublicForwards)

---

## 6. Telegram Business API

**Source:** [https://core.telegram.org/api/business](https://core.telegram.org/api/business)

### What it is

Telegram Business is a set of features for **regular Telegram user accounts** (not bots) that enable business-oriented functionality. As of the latest documentation, all Business features require a **Telegram Premium** subscription. Business accounts are regular user accounts — not a separate account type.

The Business API is implemented entirely in the **MTProto API** (account.* and messages.* methods). It is **not available via the Bot API**.

### Supported Features

#### Opening Hours
- **Method:** `account.updateBusinessWorkHours`
- Set weekly time intervals (max 28 intervals, specified in minutes-of-week).
- Timezone set via `timezone_id` (from `help.getTimezonesList`).
- Server computes `open_now` flag automatically.
- Updates emit `updateUser` to all sessions.

#### Business Location
- **Method:** `account.updateBusinessLocation`
- `address` (mandatory, max 96 UTF-8 chars) + optional `geo_point` (lat/long coordinates).
- If `geo_point` is set, advertised to nearby users feature.
- If address is set, the user's geolocation cannot be changed via `contacts.getLocated` (returns `BUSINESS_ADDRESS_ACTIVE`).

#### Quick Reply Shortcuts
- Preset message bundles (text, formatting, links, stickers, media, files).
- **Fetch:** `messages.getQuickReplies`, `messages.getQuickReplyMessages`.
- **Create/Add:** Use standard `messages.sendMessage` / `messages.sendMedia` / `messages.sendMultiMedia` / `messages.forwardMessages` with `peer=inputPeerSelf` and `quick_reply_shortcut` flag set.
- **Send:** `messages.sendQuickReplyMessages` — only in private chats with other users.
- **Edit message:** `messages.editMessage` with `quick_reply_shortcut_id`.
- **Delete message:** `messages.deleteQuickReplyMessages`.
- **Rename shortcut:** `messages.editQuickReplyShortcut`.
- **Reorder shortcuts:** `messages.reorderQuickReplies`.
- **Delete shortcut:** `messages.deleteQuickReplyShortcut`.
- Limits: `appConfig.quick_replies_limit` max shortcuts; `appConfig.quick_reply_messages_limit` max messages per shortcut. Exceeding returns `QUICK_REPLIES_TOO_MUCH` or `REPLY_MESSAGES_TOO_MUCH`.

#### Greeting Messages
- **Method:** `account.updateBusinessGreetingMessage`
- Auto-sent to new users messaging for the first time, or after configurable inactivity period (`no_activity_days`).
- Configurable by recipient type: existing chats, new chats, contacts, non-contacts, specific user exclusions.
- References a quick reply shortcut via `shortcut_id`.

#### Away Messages
- **Method:** `account.updateBusinessAwayMessage`
- Auto-sent when offline or during specific time periods.
- Schedule types: always, outside work hours, custom date range.
- Can be restricted to offline-only mode (`offline_only` flag).
- Same recipient filtering as greeting messages.

#### Business Introduction (Profile Page)
- **Method:** `account.updateBusinessIntro` (inferred from schema; `inputBusinessIntro` constructor).
- `title` (string), `description` (string), optional `sticker` (document).
- Sets a custom intro section on the business account profile.

#### Business Chatbot Support
- Business accounts can connect a bot to handle incoming messages.
- The bot receives messages from the business account's private chats and can respond on the account's behalf.
- Messages sent by the business bot are marked with `via_business_bot_id`.

#### Paid Messages (Stars)
- `send_paid_messages_stars` field on `userFull` — indicates cost in Stars for sending a paid message to this user.
- Managed via `account.*` methods in MTProto.

#### Suggested Posts
- Introduced July 1, 2025.
- `suggested_post` field on `message` constructor (`SuggestedPost` type).
- Allows channels to crowdsource content from external parties; payment via Stars or TON after posting.
- `paid_suggested_post_stars` and `paid_suggested_post_ton` flags on `message` constructor.

### Historical Availability

Telegram Business features announced and launched in early 2024. Business API documented at `core.telegram.org/api/business`. Suggested Posts launched July 2025.

### Official Documentation

- [https://core.telegram.org/api/business](https://core.telegram.org/api/business)

---

## 7. Telegram Ads / Sponsored Messages

**Source:** [https://core.telegram.org/api/sponsored-messages](https://core.telegram.org/api/sponsored-messages) · [https://ads.telegram.org](https://ads.telegram.org)

### Sponsored Messages API (MTProto — for Client Rendering)

The `messages.getSponsoredMessages` MTProto method is for **rendering** sponsored messages in client apps, not for buying or placing ads. Every Telegram client that displays channel content or bots must call this and display results.

**`messages.getSponsoredMessages#3d6ce850`:**
- Called when opening a channel/bot chat.
- Result cached for **5 minutes**.
- Returns `messages.sponsoredMessages` with `posts_between`, `start_delay`, `between_delay` fields.

**Sponsored message fields:**
- `random_id`, `url`, `title`, `message`, `button_text`, `sponsor_info`, `additional_info`.
- Optional `photo`, `media`, `color`, `recommended` flag, `can_report` flag.
- `min_display_duration`, `max_display_duration` (for video ads).

**Sponsored video ads:** Triggered during fullscreen video playback; time-based display with min/max durations.

**Sponsored search results:** `contacts.getSponsoredPeers` — sponsored channels appear in global search results alongside organic results.

**Counting & Click reporting:** `messages.viewSponsoredMessage`, `messages.clickSponsoredMessage` (with `media` and `fullscreen` flags).

**Reporting:** `messages.reportSponsoredMessage` — three-step flow: choose reason → report → result is either `adsHidden` (if Premium user), `reported`, or `chooseOption` (select reason).

**Ad Revenue for Owners:** Channel/bot owners receive **50% of ad revenue** from ads displayed in their channel. Revenue is withdrawable via `stats.*` methods — see [https://core.telegram.org/api/revenue](https://core.telegram.org/api/revenue).

### Buying Ads (Telegram Ads Platform)

The ad-buying platform is at [https://ads.telegram.org](https://ads.telegram.org). There is **no programmatic API for buying ads**. Ad placement is done via the web dashboard. Key facts:
- Targets channels with **1,000+ subscribers**.
- Minimum direct account: **€2,000,000** spend commitment.
- Via reseller agencies: typically **€3,000–€5,000** minimum deposit.
- Pricing: **CPM denominated in TON** (switched from EUR/USD to TON in 2025).
- CPM floor: approximately **0.1 TON per 1,000 impressions**.

**Third-party app obligation:** Any third-party app using the Telegram API that displays channel content **must** implement and display sponsored messages (deadline: January 1, 2022, for existing apps). Failure to comply results in API access revocation.

### Official Documentation

- Sponsored Messages API: [https://core.telegram.org/api/sponsored-messages](https://core.telegram.org/api/sponsored-messages)
- Ad Platform: [https://ads.telegram.org](https://ads.telegram.org)
- Revenue API: [https://core.telegram.org/api/revenue](https://core.telegram.org/api/revenue)
- Pavel Durov's announcement: [https://t.me/durov/172](https://t.me/durov/172)

---

---

# PART 2: UNSUPPORTED FEATURES

---

### 2.1 Statistics API — Unsupported

| Feature | Status | Notes |
|---|---|---|
| Statistics via Bot API (JSON) | **Not supported** | `getChatStatisticsURL` in Bot API returns a URL/PNG, not JSON data. Structured JSON access requires MTProto. |
| Real-time statistics | **Not supported** | Stats appear to update approximately daily; no real-time or streaming stats endpoint exists. |
| Individual subscriber identity in stats | **Not supported** | `languages_graph`, `new_followers_by_source_graph` are aggregated; no per-user breakdown. |
| Historical stats beyond the returned period | **Not supported** | The period is determined by Telegram server; cannot request arbitrary historical ranges. |
| Bulk CSV/spreadsheet export | **Not supported** | No official export format. Data must be parsed from JSON graph format. |
| Stats for channels below the size threshold | **Not supported** | `can_view_stats` flag is server-determined by channel size; small channels cannot access the Stats API. |

### 2.2 Bot API — Unsupported

| Feature | Status | Notes |
|---|---|---|
| Seeing messages from other bots | **Not supported** | Bots cannot receive messages sent by other bots in any context. By design. |
| Initiating conversations with users | **Not supported** | Bots can only message users who have previously interacted (started) with the bot. |
| Upload files > 50MB | **Not supported** (default) | Workaround: self-hosted Bot API server, which supports up to 2GB. |
| Download files > 20MB via `getFile` | **Not supported** | Only files under 20MB can be downloaded through the Bot API `getFile`. |
| Creating/joining channels or groups | **Not supported** | Bots can be added to chats by users but cannot create or join chats autonomously. |
| Managing business account settings | **Not supported** | Business features are only available via MTProto as user-account operations. |
| Access secret chats | **Not supported** | Secret chats are device-local E2E and not accessible via bots or the Bot API. |
| Long polling + webhook simultaneously | **Not supported** | Only one update retrieval method at a time. |
| Programmatic ad buying | **Not supported** | No API for placing ads. Must use the ads.telegram.org web dashboard. |

### 2.3 Business API — Unsupported

| Feature | Status | Notes |
|---|---|---|
| Business features without Premium | **Not supported** | All Telegram Business features require Telegram Premium subscription. |
| Business features via Bot API | **Not supported** | Business API is MTProto-only (account.* and messages.* user-account methods). |
| Verified business badge (like WhatsApp) | **Not confirmed as supported** | Telegram has `bot_verification` field in schema (via bots), but a verified badge equivalent to WhatsApp Business is not documented in the public Business API. |
| Automated invoice/CRM integration API | **Not supported** | No native CRM or invoice management API within Telegram Business. |

### 2.4 Sponsored Messages / Ads — Unsupported

| Feature | Status | Notes |
|---|---|---|
| Programmatic ad buying API | **Not supported** | No REST or MTProto method for buying ads. Web dashboard only. |
| Targeting individual users | **Not supported** | Sponsored messages target channels by category/keyword. No user-level targeting. |
| Hiding sponsored messages (without Premium) | **Not supported** | Reporting a sponsored message may hide ads for Premium subscribers only. |
| Third-party apps skipping sponsored messages | **Not supported / prohibited** | Third-party Telegram client apps are required by Telegram's terms to display sponsored messages. API access is revoked if they do not. |

---

---

# PART 3: POSSIBLE WORKAROUNDS

---

### 3.1 Statistics Access Without MTProto

**Problem:** Developer has only Bot API access and needs structured statistics data.

**Workarounds:**
1. **Switch to MTProto:** Use a library like Telethon (Python), Pyrogram (Python), GramJS (JS/TS), or mtcute (TS) to access `stats.getBroadcastStats` via user-account authentication.
2. **Third-party analytics services:** TGStat, Telemetr.io, and similar services scrape and expose Telegram channel stats via their own APIs (not official Telegram APIs). These are unofficial and subject to Telegram's ToS.
3. **Telegram Desktop export:** Export chat history as JSON (limited to message content, not analytics) via the desktop client's Export feature.
4. **Telethon/Pyrogram bot mode:** Log in as a bot via MTProto libraries (Telethon supports bot token auth), which gives access to the full MTProto schema even for bots — though admin-gated stats still require an admin user session.

### 3.2 File Size Limit for Bot API

**Problem:** Need to handle files > 50MB or download files > 20MB.

**Workarounds:**
1. **Self-hosted Bot API:** Telegram provides open-source code for the Bot API server. Self-hosting raises the upload limit to 2GB (Premium users) and removes the 20MB download restriction.
2. **Switch to MTProto (TDLib/Telethon/Pyrogram):** Handles up to 2GB (4GB for Premium) natively.

### 3.3 Bot-to-Bot Communication

**Problem:** Bots cannot see messages from other bots.

**Workarounds:**
1. **Shared external state:** Use a shared Redis, database, or message queue that both bots write to and read from.
2. **MTProto user account as proxy:** A user-account (via MTProto) can see messages from bots and can relay or process them.
3. **Inline results:** Bot A can send inline query results that Bot B processes indirectly through user interaction.

### 3.4 Broadcast Rate Limits

**Problem:** Need to send to >30 users/second without paying for Paid Broadcasts.

**Workarounds:**
1. **Spread over time:** Stagger sends over 8–12 hours as recommended in official docs.
2. **Paid Broadcasts:** Enable Paid Broadcasts in `@BotFather` (requires 100,000 Stars + 100,000 MAUs).
3. **Multiple bots:** Distribute recipients across multiple bot accounts (each gets their own 30 msg/sec budget). This is a gray area regarding ToS compliance.

### 3.5 Accessing Business Features Without Full MTProto Implementation

**Problem:** Developer wants to use Business features but only knows Bot API.

**Workarounds:**
1. **Bot connected to Business Account:** A regular Telegram bot can be connected to a business account via the Telegram Business settings. The bot then receives messages from the business account's private chats and can respond — this is accessed through the standard Bot API, with messages containing the `business_connection_id` field.
2. **Use Telethon/Pyrogram as user-account automation:** Log in as the business account user and call MTProto business methods directly. (Note: Telegram's ToS restricts mass automation of user accounts; use judiciously.)

### 3.6 Programmatic Ad Buying

**Problem:** Need to buy/manage ads programmatically.

**Workarounds:**
1. **Use reseller agencies:** Agencies that access ads.telegram.org can offer their own APIs or dashboards.
2. **AdsGram and similar networks:** Third-party ad networks (AdsGram, etc.) serve ads within Telegram Mini Apps and bots and offer programmatic APIs. These are not official Telegram Ads but reach Telegram users.
3. **Suggested Posts (July 2025):** Advertisers can propose posts to channel owners via the Suggested Posts feature, with payment in Stars or TON. This is a programmatic-adjacent workflow but still requires manual channel owner approval.

---

---

# PART 4: OPEN QUESTIONS

---

1. **Statistics refresh rate:** The official documentation does not specify how frequently stats data is updated server-side (hourly, daily?). The `period` field is dynamic. This remains undocumented.

2. **Minimum channel size for Stats API:** The threshold for `can_view_stats` to become `true` is described as "a server-side config" — the exact subscriber count required is not publicly documented and may change without notice.

3. **Bot API Business Connection:** The `business_connection_id` field was introduced in Bot API 7.2 (February 2024) but the full specification of what the bot can and cannot do on behalf of the business account is partially documented. Specifically: can a connected bot programmatically manage business settings (working hours, away messages) via the Bot API, or is this still MTProto-only even for connected bots?

4. **Verified Business Badges:** The `bot_verification` field appears in the `userFull` and `channelFull` schemas, suggesting a bot-granted verification mechanism. The full specification, eligibility requirements, and whether this results in a visible "verified" badge are not clearly documented in the public API docs.

5. **TDLib version and layer currency:** The current TDLib release version and the Telegram API layer it supports are not reflected in the documentation in real-time. The `NuGet Gallery | TDLib 1.8.64.1` suggests the last published version, but the master branch on GitHub may be ahead.

6. **Paid Messages for non-Business users:** The `send_paid_messages_stars` field on `userFull` suggests users can require Stars to receive messages. Whether this is exclusive to Business accounts or available to all users with Premium is not clearly specified.

7. **Stars-based ads budget management:** Whether channel owners can programmatically manage their Stars balance for running ad campaigns or only view revenue via the API is unclear from available documentation.

8. **Data retention for statistics:** Telegram's documentation does not specify how far back statistics data is retained on the server. Third-party tools suggest ~12 months, but this is not confirmed officially.

9. **GDPR/export compliance:** No official mechanism for exporting analytics data in a machine-readable, GDPR-compliant format on behalf of channel subscribers. Whether the raw `statsGraph.json` satisfies data portability requirements is an open legal/technical question.

10. **Rate limits for MTProto Stats methods:** `stats.getBroadcastStats` and related methods have no published rate limits. Practical limits exist (FLOOD_WAIT errors), but thresholds are not documented.

---

---

# Sources

All facts in this report are cited from official Telegram documentation unless otherwise noted.

- [Telegram Bot API Reference](https://core.telegram.org/bots/api)
- [Telegram Bot Features](https://core.telegram.org/bots/features)
- [Bots FAQ](https://core.telegram.org/bots/faq)
- [Bot API Changelog](https://core.telegram.org/bots/api-changelog)
- [Bot Payments API](https://core.telegram.org/bots/payments)
- [Telegram APIs Index](https://core.telegram.org/)
- [MTProto Protocol](https://core.telegram.org/mtproto)
- [TDLib Overview](https://core.telegram.org/tdlib)
- [Getting Started with TDLib](https://core.telegram.org/tdlib/getting-started)
- [TDLib GitHub](https://github.com/tdlib/td)
- [Channel Statistics API](https://core.telegram.org/api/stats)
- [stats.getBroadcastStats](https://core.telegram.org/method/stats.getBroadcastStats)
- [stats.getMegagroupStats](https://core.telegram.org/method/stats.getMegagroupStats)
- [stats.getMessageStats](https://core.telegram.org/method/stats.getMessageStats)
- [stats.getMessagePublicForwards](https://core.telegram.org/method/stats.getMessagePublicForwards)
- [Business API](https://core.telegram.org/api/business)
- [Admin, Banned, Default Rights](https://core.telegram.org/api/rights)
- [chatAdminRights constructor](https://core.telegram.org/constructor/chatAdminRights)
- [Sponsored Messages API](https://core.telegram.org/api/sponsored-messages)
- [Telegram Ads Platform](https://ads.telegram.org)
- [Telethon: HTTP Bot API vs MTProto](https://docs.telethon.dev/en/stable/concepts/botapi-vs-mtproto.html)
- [mtcute: MTProto vs. Bot API](https://mtcute.dev/guide/intro/mtproto-vs-bot-api)
- [TDLib API Method Reference](https://core.telegram.org/tdlib/docs/classtd_1_1td__api_1_1_function.html)

---

*Report generated: July 3, 2026. All claims verified against official Telegram documentation. No implementation code included.*
