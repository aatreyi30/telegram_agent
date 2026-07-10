"""Named cadence constants for every job in schedulers.py.

Single source of truth for "how often" — schedulers.py used to hardcode the
same number twice per job (once in the APScheduler trigger, once in the
human-readable label string), which let them silently drift apart (see
MONTHLY_REPORT_TIME below: the old label said "1st 00:00" while the trigger
actually fired at 00:05). Import these constants and build the trigger+label
pair with the helpers in schedulers.py instead of writing numbers inline.
"""

from __future__ import annotations

# --- interval jobs (minutes) ---
TELEGRAM_SYNC_MIN = 5
COMPETITOR_SYNC_MIN = 10
NORMALIZE_POSTS_MIN = 5
STATS_REFRESH_MIN = 30
DEAL_RANKING_MIN = 30  # Phase 3.2 -- DealScoringEngine (job body replaces the earlier no-op stub)
LINK_RESOLUTION_DEFAULT_MIN = 15  # overridden at runtime by settings.link_resolve_interval_min
QUEUE_PROCESSOR_MIN = 1
MERCHANT_FEED_SYNC_MIN = 30
NOTIFICATION_ENGINE_MIN = 5
OUTCOME_COLLECTOR_MIN = 15  # Phase 2.3 -- advances post_outcomes through 1h/6h/24h

# --- interval jobs (hours) ---
DEAL_MONITORING_HOURS = 2
PRICE_HISTORY_HOURS = 6
DEAL_EXPIRY_HOURS = 1
URL_HEALTH_HOURS = 12
ANALYTICS_AGGREGATION_HOURS = 1
ORG_HEALTH_HOURS = 1

# --- daily cron jobs — (hour, minute) in IST ---
LEARNING_TIME = (2, 0)
DB_CLEANUP_TIME = (3, 0)
DAILY_REPORT_TIME = (5, 15)
DAILY_PLAN_TIME = (5, 30)
GROWTH_DETECTION_TIME = (6, 0)
COMPETITOR_DISCOVER_TIME = (6, 30)
COMPETITOR_INTEL_TIME = (7, 0)
AI_DAILY_SUMMARY_TIME = (8, 0)

# --- weekly / monthly cron jobs ---
WEEKLY_RETRO_TIME = (7, 30)  # Phase 2.4 -- must run before WEEKLY_REPORT_TIME
WEEKLY_REPORT_DOW = "mon"
WEEKLY_REPORT_TIME = (8, 30)
MONTHLY_REPORT_DAY = 1
MONTHLY_REPORT_TIME = (0, 5)
