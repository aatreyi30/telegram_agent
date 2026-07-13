export interface PageMeta { total: number; page: number; page_size: number; pages: number; }

export interface ChannelOverview { available: boolean; title?: string; username?: string; subscribers?: number; }

export interface PublishingGate { name: string; ok: boolean; detail: string; }

export interface OverviewResponse {
  channel: ChannelOverview; posts: number; competitors: number; drafts: number;
  queue_counts: Record<string, number>; affiliate_provider: string; publishing_gates: PublishingGate[];
}

export interface GrowthDailyPoint { date: string; subs_end: number | null; joined: number; left: number; net: number; }

// Telegram's admin-only "views by source" / "joins by source" breakdown (requires
// Channel.can_view_stats). Absent (undefined/null) when the channel doesn't qualify.
export interface SourceBreakdown {
  totals: Record<string, number>;
  daily: Record<string, Record<string, number>>;
}

export type GrowthResponse =
  | { available: true; current: number | null; joined: number; left: number; net: number; days: number;
      first_date: string; last_date: string; daily: GrowthDailyPoint[];
      view_sources?: SourceBreakdown | null; follower_sources?: SourceBreakdown | null; }
  | { available: false; reason: string; current: number | null; days: number;
      view_sources?: SourceBreakdown | null; follower_sources?: SourceBreakdown | null; };

export interface GrowthRecommendation {
  priority: number; category: string; recommendation: string; reasoning: string;
  evidence: Record<string, unknown>; confidence: number; expected_outcome: string | null;
}

export interface ReasonedInsightDTO {
  metric: string; direction: "up" | "down"; change: number | null; unit: string | null;
  observation: string; why: string; period: string; evidence: Record<string, unknown>; confidence: number;
}

export interface PostTypePerformanceDTO {
  post_type: string; posts: number; share: number; avg_views_per_day: number | null; rank: number;
}

export interface GrowthBlueprint {
  available: boolean; mode?: "cold_start" | "optimization"; channel_type?: string;
  blueprint?: Record<string, unknown>; confidence?: number;
}

export interface ChannelStyleProfile {
  available: boolean; avg_caption_len?: number | null; top_emojis?: [string, number][] | null;
  cta_rate?: number | null; coupon_rate?: number | null; multi_deal_rate?: number | null;
  media_rate?: number | null; posts_per_day?: number | null; top_hours_ist?: [number, number][] | null;
}

export interface EmojiRuleDTO { emoji: string; lift_pct: number; avg_with: number; baseline: number; sample: number; }

export interface EmojiPolicy { lead: string[]; avoid: string[]; rules: EmojiRuleDTO[]; window: string; }

export interface ContentMixRow {
  post_type: string; current_share: number | null; target_share: number | null;
  avg_views_per_day: number | null; action: "increase" | "maintain" | "decrease" | string;
}

export interface InsightsResponse {
  recommendations: GrowthRecommendation[]; reasoning: ReasonedInsightDTO[];
  performance: PostTypePerformanceDTO[]; content_mix: ContentMixRow[] | null; date_filtered: boolean;
  blueprint: GrowthBlueprint; style: ChannelStyleProfile; emoji_policy: EmojiPolicy;
}

export interface MetricBucket {
  label: string; n: number; avg_views: number; median_views: number; total_views: number;
  total_reactions: number; total_forwards: number;
  total_engagement: number; engagement_rate: number; cta_posts: number; deal_posts: number;
}

export interface GoldenHour extends MetricBucket { hour: string; }

export interface AnalyticsWindow { source: string; start: string | null; end: string | null; days: number; months: number; n: number; }

export interface AnalyticsResponse {
  window: AnalyticsWindow; timeline: MetricBucket[]; by_hour: MetricBucket[]; by_weekday: MetricBucket[];
  by_type: MetricBucket[]; by_merchant: MetricBucket[]; golden_hours: GoldenHour[]; growth: GrowthResponse;
  total_posts: number; total_views: number; total_reactions: number; total_forwards: number;
  total_engagement: number; engagement_rate: number; cta_rate: number; deal_rate: number;
}

export interface DataRangeResponse { min: string | null; max: string | null; }

export interface DayMerchantRow {
  key: string | null; display_name: string; post_count: number; total_views: number;
  total_reactions: number; total_forwards: number; total_engagement: number;
  engagement_rate: number | null; deal_count: number;
  type_dist: Record<string, number>; top_post: { views: number; preview: string } | null;
}

export interface DayBaseline { avg_posts_per_day: number; avg_views_per_post: number; window: string; }

export type DayResponse =
  // `date_end` is only present when a range (start !== end) was requested — a plain
  // single-date lookup keeps the original shape unchanged.
  | { date: string | null; date_end?: string; available: false; note: string; }
  | { date: string; date_end?: string; available: true; posts: number; merchantless_count: number;
      total_views: number; avg_views_per_post: number;
      merchants: DayMerchantRow[]; type_mix: [string, number][]; merchant_mix: [string, number][];
      baseline: DayBaseline; vs_baseline: { posts_delta: number; views_delta_pct: number | null; }; };

export interface WhyThisDeal {
  rank_score: number | null; merchant: string | null; discount_percent: number | null;
  score_breakdown: Record<string, unknown> | null; why: string; deal_count?: number;
}

export interface StrategyRationale {
  kind: string; period: string; emoji_policy: EmojiPolicy;
  target_window_ist?: { part: string; hours: string; avg_views_per_day: number; why: string; };
  why_type?: string; why_this_deal?: WhyThisDeal; note?: string;
}

export interface DraftItem {
  id: number; post_type: string; status: string; bucket: string | null; rank_score: number | null;
  text: string; affiliate_status: string | null;
  emoji_policy: Partial<EmojiPolicy> | null; rationale: StrategyRationale | null;
  generated_at: string | null;
}

export interface DraftsResponse extends PageMeta { items: DraftItem[]; }

export interface PostItem { id: number; posted_at: string | null; views: number | null; forwards: number | null; preview: string; links: string[]; }

export interface PostsResponse extends PageMeta { items: PostItem[]; }

export interface QueueItem {
  id: number; post_id: number | null; channel: string | null; category: string | null;
  status: string; scheduled_at: string | null; attempts: string; note: string;
}

export interface QueueResponse extends PageMeta { counts: Record<string, number>; items: QueueItem[]; }

export interface CompetitorBenchmarkRow { dimension: string; owned_value: number | null; competitor_value: number | null; delta: number | null; }

export interface CompetitorEntity {
  id?: number;
  name: string; is_owned?: boolean; category?: "platform" | "channel" | "unclassified";
  subscribers?: number | null;
  posts_per_day?: number | null; avg_views_per_post?: number | null;
  emoji_rate?: number | null; cta_rate?: number | null; coupon_rate?: number | null;
  hashtag_rate?: number | null; media_rate?: number | null; avg_links?: number | null;
  deal_mix?: Record<string, number>; merchant_mix?: Record<string, number>;
  similarity_to_us?: number | null; benchmarks?: CompetitorBenchmarkRow[];
  posts_per_hour_ist?: Record<string, number>; weekday_distribution?: Record<string, number>;
  posts?: number; tenure_label?: string;
  [key: string]: any;
}

// GET /competitors — Settings > Competitors tab. Raw `competitors` table rows (every
// competitor, including freshly-added ones with no profile yet) — distinct from
// CompetitorEntity (the comparison/dashboard entity, PROFILED competitors only).
// Management CRUD (edit/delete) needs every row's `id`.
export interface CompetitorRow {
  id: number; username: string; title: string | null;
  category: "platform" | "channel" | null; status: string;
  last_collected_at: string | null; posts: number;
  monitoring_enabled: boolean;
  [key: string]: any;
}

export interface CompetitorsResponse { competitors: CompetitorRow[]; }

export interface CompetitorDashboardResponse {
  summary: { total: number; platform: number; channel: number; };
  platform: CompetitorEntity[]; channel: CompetitorEntity[];
  unavailable: string[]; note: string; metrics: string[]; applied_window: number | null;
}

// GET /competitors/{id}/trends — day-bucketed series for the per-competitor detail page.
// Row/field shapes are treated loosely (index signatures) since the endpoint is being built
// concurrently; the detail page picks whichever keys are actually present defensively.
export interface CompetitorTrendPoint { date: string; [key: string]: any; }

export interface CompetitorTopPost {
  post_id?: number; views?: number | null; forwards?: number | null; reactions?: number | null;
  caption?: string | null; posted_at?: string | null; [key: string]: any;
}

export interface CompetitorHistogramBucket { bucket?: string; label?: string; count?: number; [key: string]: any; }

// GET /competitor-dashboard/trends — posts/day & views/day for every competitor at
// once, sharing one calendar window, keyed by competitor name for direct MultiLineChart use.
export interface CompetitorDashboardTrendsResponse {
  dates: string[];
  posting_trend: CompetitorTrendPoint[];
  views_trend: CompetitorTrendPoint[];
  competitors: { id: number; name: string }[];
}

export interface CompetitorTrendsResponse {
  posting_trend: CompetitorTrendPoint[];
  views_trend: CompetitorTrendPoint[];
  merchant_trend: CompetitorTrendPoint[];
  top_posts: CompetitorTopPost[];
  content_mix_trend: CompetitorTrendPoint[];
  media_text_trend: CompetitorTrendPoint[];
  link_usage_trend: CompetitorTrendPoint[];
  caption_length_distribution: CompetitorHistogramBucket[];
  posting_consistency: { stdev?: number | null; variance?: number | null; daily?: CompetitorTrendPoint[]; [key: string]: any };
  [key: string]: any;
}

export interface DealTypeAllocation { deal_type: string; post_type: string; target_posts: number; avg_views_per_day: number | null; }
export interface MerchantAllocation { merchant: string; recent_share: number; }
export interface PostingWindowRow { part: string; hours: string; posts: number; }
export interface DailyThemeRow { day: string; date: string; theme_focus: string; posts_planned: number; }
export interface UpcomingEventRow { name: string; date: string; days_away: number; date_confidence: string; }
export interface PlanRisk { kind?: string; detail: string; [key: string]: unknown; }

export interface DailyPlanBlueprint {
  posts_planned: number; posting_windows: PostingWindowRow[];
  deal_type_allocation: DealTypeAllocation[]; merchant_allocation: MerchantAllocation[];
  emoji_strategy: string[] | null; event_note: string | null;
}

export interface WeeklyPlanBlueprint {
  posts_per_day: number; posts_per_week: number; daily_themes: DailyThemeRow[];
  rotation_for_diversity: string[]; upcoming_events: UpcomingEventRow[];
}

export interface EventPlanBlueprint {
  event: string; event_date: string; days_away: number; window_days: number;
  date_confidence: "exact" | "approximate" | string;
  recommended_posts_per_day_during_event: number; baseline_posts_per_day: number;
  ramp_multiplier: number; merchant_focus: string; prep_checklist: string[]; notes: string | null;
}

export type CampaignPlanDTO =
  | { plan_type: "daily"; title: string; target_date: string | null; end_date: string | null;
      confidence: number; blueprint: DailyPlanBlueprint;
      expected_outcome: { estimated_daily_views: number; basis: string; caveat: string } | null;
      risks: PlanRisk[] | null; evidence: Record<string, unknown> | null; }
  | { plan_type: "weekly"; title: string; target_date: string | null; end_date: string | null;
      confidence: number; blueprint: WeeklyPlanBlueprint;
      expected_outcome: { note: string } | null; risks: null; evidence: Record<string, unknown> | null; }
  | { plan_type: "event"; title: string; target_date: string | null; end_date: string | null;
      confidence: number; blueprint: EventPlanBlueprint;
      expected_outcome: { note: string } | null;
      risks: PlanRisk[] | null; evidence: Record<string, unknown> | null; }
  | { plan_type: string; title: string; target_date: string | null; end_date: string | null;
      confidence: number; blueprint: Record<string, unknown>;
      expected_outcome: Record<string, unknown> | null;
      risks: PlanRisk[] | null; evidence: Record<string, unknown> | null; };

export type PlansResponse = CampaignPlanDTO[];

export interface WeeklyResponse {
  available: boolean;
  weekly_plan: { title: string; blueprint: WeeklyPlanBlueprint; expected_outcome: { note: string } | null; confidence: number; generated_at: string | null; } | null;
  what_changed: ReasonedInsightDTO[]; recommendations: GrowthRecommendation[]; ai_summary: string | null;
}

// Editable post-text templates stored in org.settings.post_templates. Every key is
// optional in the type (a fresh org may not have overridden them yet) but the backend
// seeds all 11; the settings editor prefills from whatever the GET returns.
export interface PostTemplates {
  single_loot_badge?: string;
  single_price?: string;
  single_coupon_line?: string;
  collection_theme_default?: string;
  collection_item?: string;
  collection_footer?: string;
  category_theme_with_tier?: string;
  category_theme_no_tier?: string;
  category_item?: string;
  category_coupon_suffix?: string;
  observed_collection_theme?: string;
  fallback_category_label?: string;
  fallback_title?: string;
}

export type PostTemplateKey = keyof PostTemplates;

export interface OrgSettings {
  grabon_shortener_url?: string; grabon_amazon_tag?: string; grabon_flipkart_params?: string;
  grabon_shorten_all?: boolean; preferred_categories?: string[];
  auto_discover_competitors?: boolean; post_templates?: PostTemplates; [key: string]: unknown;
}

export interface OrgResponse { id: number; key: string; name: string; affiliate_provider: string; settings: OrgSettings; channels: number; }

export interface ChannelDTO { id: number; username: string | null; title: string | null; kind: "owned" | "competitor"; status: "pending" | "active" | string; resolved: boolean; org_id: number | null; posts: number; }

export interface AuthUser { id: number; org_id: number; name: string; email: string | null; role: "owner" | "editor" | "viewer"; }

export interface UserAccount { id: number; org_id: number; name: string; email: string | null; role: "owner" | "editor" | "viewer"; has_password: boolean; last_login_at: string | null; }

export type UsersResponse = UserAccount[];
export type ChannelsResponse = ChannelDTO[];

export interface LoginResponse { token: string; user: AuthUser; }

export interface DigestPlanSlot { type: string; window_ist: string; theme: string; why?: string; }

export interface DigestPlan { post_slots?: DigestPlanSlot[]; emphasis?: string; watch?: string; }

export interface ReconciliationAdherence {
  planned: number; published: number; matched: number; missed_windows: string[];
  by_type: { planned: Record<string, number>; published: Record<string, number>; };
}

export interface ReconciliationAttributionItem { metric: string; expected: number; actual: number | null; gap: number | null; }

export interface ReconciliationAttribution { items: ReconciliationAttributionItem[]; correlational: boolean; caveat: string; }

export interface Reconciliation { adherence: ReconciliationAdherence; attribution: ReconciliationAttribution; caveat: string; }

export type DigestResponse =
  | { available: false; digest: ""; plan: null; factcheck_status: null; reconciliation: null; generated_at: null; }
  | { available: true; digest: string; plan: DigestPlan | null; factcheck_status: string | null;
      reconciliation: Reconciliation | null; generated_at: string | null; };

export interface YesterdayBrief {
  source: "report" | "live" | "none";
  posts_count: number; views_total: number; views_avg: number; views_median: number;
  reactions_total: number; forwards_total: number; engagement_rate: number;
  top_post_id: number | null;
  type_mix: Record<string, number> | null;
  category_mix: Record<string, number> | null;
  best_category: string | null; worst_category: string | null;
  subs_net: number | null;
}

export interface TrajectoryDay { date: string; posts: number; views_avg: number; }

export interface DailyTrajectory {
  days: TrajectoryDay[];
  recent_cadence: number;
  lifetime_baseline: number | null;
}

export interface DailySlot { type: string; window_ist: string; count?: number | null; theme: string; merchant?: string | null; why: string; }

export interface DailyPlanToday {
  recommended_posts: number;
  cadence_why: string;
  posting_windows: PostingWindowRow[];
  deal_type_allocation: { deal_type: string; target_posts: number; avg_views_per_day: number | null }[];
  merchant_allocation: MerchantAllocation[];
  slots: DailySlot[];
  emphasis: string | null; watch: string | null;
  risks: PlanRisk[] | null;
  confidence: number;
  scheduled_count: number;
  gap: number;
  plan_clamped: boolean;
}

export interface UpcomingEventBrief { name: string; days_away: number; date_confidence: string; }

export interface DailyBrief {
  available: boolean;
  reason?: string;
  date: string;
  prev_date: string;
  min_date: string; max_date: string;
  yesterday: YesterdayBrief | null;
  trajectory: DailyTrajectory;
  today: DailyPlanToday;
  digest: string;
  factcheck_status: "pass" | "warn" | null;
  ai_available: boolean;
  upcoming_event: UpcomingEventBrief | null;
  operator_directive?: string | null;
  can_regenerate?: boolean;
}

export interface WeeklyBriefDay {
  date: string; weekday: string; posts: number; views_avg: number;
  joined: number; left: number; net: number;
}

export interface WeeklyBriefTheme { day: string; date: string; theme_focus: string; posts_planned: number; }

export interface WeeklyBriefTotals { posts: number; views_total: number; avg_posts_per_day: number; }

export interface WeeklyBrief {
  available: boolean; reason?: string;
  week_start: string; week_end: string;
  days: WeeklyBriefDay[];
  totals: WeeklyBriefTotals;
  themes: WeeklyBriefTheme[];
  recommended_posts_per_day: number;
  upcoming_events: UpcomingEventRow[];
  digest: string;
  ai_available: boolean;
  operator_directive?: string | null;
  can_regenerate?: boolean;
}

// GET /retro/latest — Phase 2.4 weekly retro: prediction accuracy, rule-based
// adjustments for next week's plan, and the engagement/churn readout it's based on.
export interface RetroPrediction { mape_views_24h: number | null; n_posts: number; bias: number | null; }

export interface RetroMiss {
  post_id: number; pred: number | null; actual: number | null;
  type: string | null; merchant: string | null;
}

export interface RetroPlanAdherence { planned: number; published: number; blocked_stale: number; skipped: number; }

export interface RetroEngagement {
  median_forward_rate: number | null; best_hour_bucket: string | null; best_type_by_engagement: string | null;
}

export interface RetroChurnVsFrequency {
  high_leave_days_posts_per_day: number | null; low_leave_days_posts_per_day: number | null;
}

export interface RetroMetrics {
  prediction: RetroPrediction;
  top_over: RetroMiss[]; top_under: RetroMiss[];
  plan_adherence: RetroPlanAdherence;
  engagement: RetroEngagement;
  churn_vs_frequency: RetroChurnVsFrequency;
  adjustments: string[];
}

export type RetroLatest =
  | { available: false; week_start: null; metrics: null; narrative: null; }
  | { available: true; week_start: string; metrics: RetroMetrics; narrative: string | null; created_at?: string | null; };

// GET /deals/scored — Phase 3.3 audience-aware deal score from the scheduled
// DealScoringEngine, with an explainable per-component breakdown (each 0..1).
export interface ScoredDealComponents {
  discount_depth: number; audience_affinity: number; freshness: number;
  time_fit: number; price_credibility: number; scarcity_of_coverage: number;
}

export interface ScoredDeal {
  deal_id: string; title: string | null; merchant_key: string | null;
  current_price: number | null; discount_percent: number | null; url: string | null;
  score: number; components: ScoredDealComponents; scored_at: string | null;
}

export interface ScoredDealsResponse { items: ScoredDeal[]; }

export interface SchedulerJobStatus {
  key: string; name: string; cadence: string; priority: string;
  last_status: string | null; last_detail: string | null; last_error: string | null;
  last_started_at: string | null; last_duration_ms: number | null;
  cadence_minutes: number; overdue: boolean | null;
}

export interface SchedulerRunRow {
  key: string; status: string; detail: string | null; error: string | null;
  processed: number; duration_ms: number | null; at: string | null;
}

export interface SchedulerRunsResponse { jobs: SchedulerJobStatus[]; runs: SchedulerRunRow[]; }
