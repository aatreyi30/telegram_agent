/**
 * Backend response DTOs, one file per the whole `/api/*` surface. Mirrors the
 * shapes returned by `be/src/controllers/service.py` and `be/src/controllers/accounts.py`
 * (the `{success, data, error}` envelope is already unwrapped by `services/api.ts`,
 * so these types describe the unwrapped `data`).
 *
 * Keep this in sync with the backend when a response shape changes — see
 * `plan.md`'s "What changed in the backend" section for the fields that moved
 * this session (growth payload, publishing gates, drafts rationale).
 */

// ---------------------------------------------------------------------------
// Shared primitives
// ---------------------------------------------------------------------------

export interface PageMeta {
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface ChannelOverview {
  available: boolean;
  title?: string;
  username?: string;
  subscribers?: number;
}

// ---------------------------------------------------------------------------
// GET /api/overview
// ---------------------------------------------------------------------------

export interface PublishingGate {
  name: string;
  ok: boolean;
  detail: string;
}

export interface OverviewResponse {
  channel: ChannelOverview;
  posts: number;
  competitors: number;
  drafts: number;
  queue_counts: Record<string, number>;
  affiliate_provider: string;
  publishing_gates: PublishingGate[];
}

// ---------------------------------------------------------------------------
// GET /api/growth  (and the `growth` key inside AnalyticsResponse — same shape)
// ---------------------------------------------------------------------------

export interface GrowthDailyPoint {
  date: string;
  count: number | null;
  delta: number | null;
}

export type GrowthResponse =
  | {
      available: true;
      current: number;
      first: number;
      first_date: string;
      last_date: string;
      net_change: number;
      span_days: number;
      growth_per_day: number | null;
      growth_rate_pct: number;
      snapshots: number;
      daily: GrowthDailyPoint[];
    }
  | { available: false; reason: string; snapshots: number };

// ---------------------------------------------------------------------------
// GET /api/insights
// ---------------------------------------------------------------------------

export interface GrowthRecommendation {
  priority: number;
  category: string;
  recommendation: string;
  reasoning: string;
  evidence: Record<string, unknown>;
  confidence: number;
  expected_outcome: string | null;
}

export interface ReasonedInsightDTO {
  metric: string;
  direction: "up" | "down";
  change: number | null;
  unit: string | null;
  observation: string;
  why: string;
  period: string;
  evidence: Record<string, unknown>;
  confidence: number;
}

export interface LearningDTO {
  category: string;
  statement: string;
  confidence: number;
  sample_size: number;
  how_calculated: string | null;
  period: string;
}

export interface PostTypePerformanceDTO {
  post_type: string;
  posts: number;
  share: number;
  avg_views_per_day: number | null;
  rank: number;
}

export interface GrowthBlueprint {
  available: boolean;
  mode?: "cold_start" | "optimization";
  channel_type?: string;
  blueprint?: Record<string, unknown>;
  confidence?: number;
}

export interface ChannelStyleProfile {
  available: boolean;
  avg_caption_len?: number | null;
  top_emojis?: [string, number][] | null;
  cta_rate?: number | null;
  coupon_rate?: number | null;
  multi_deal_rate?: number | null;
  media_rate?: number | null;
  posts_per_day?: number | null;
  top_hours_ist?: [number, number][] | null;
}

export interface EmojiRuleDTO {
  emoji: string;
  lift_pct: number;
  avg_with: number;
  baseline: number;
  sample: number;
}

export interface EmojiPolicy {
  lead: string[];
  avoid: string[];
  rules: EmojiRuleDTO[];
  window: string;
}

export interface InsightsResponse {
  recommendations: GrowthRecommendation[];
  reasoning: ReasonedInsightDTO[];
  learnings: LearningDTO[];
  performance: PostTypePerformanceDTO[];
  blueprint: GrowthBlueprint;
  style: ChannelStyleProfile;
  emoji_policy: EmojiPolicy;
}

// ---------------------------------------------------------------------------
// GET /api/analytics, GET /api/data-range
// ---------------------------------------------------------------------------

export interface MetricBucket {
  label: string;
  n: number;
  avg_views: number;
  total_views: number;
  avg_reactions: number;
  total_reactions: number;
  avg_forwards: number;
  total_forwards: number;
  total_engagement: number;
  engagement_rate: number;
  cta_posts: number;
  deal_posts: number;
}

export interface GoldenHours {
  by_engagement: (MetricBucket & { hour: string })[];
  by_views: (MetricBucket & { hour: string })[];
}

export interface AnalyticsWindow {
  source: string;
  start: string | null;
  end: string | null;
  days: number;
  months: number;
  n: number;
}

export interface AnalyticsResponse {
  window: AnalyticsWindow;
  timeline: MetricBucket[];
  by_hour: MetricBucket[];
  by_weekday: MetricBucket[];
  by_type: MetricBucket[];
  by_merchant: MetricBucket[];
  golden_hours: GoldenHours;
  growth: GrowthResponse;
  total_posts: number;
  total_views: number;
  total_reactions: number;
  total_forwards: number;
  total_engagement: number;
  engagement_rate: number;
  cta_rate: number;
  deal_rate: number;
}

export interface DataRangeResponse {
  min: string | null;
  max: string | null;
}

// ---------------------------------------------------------------------------
// GET /api/day
// ---------------------------------------------------------------------------

export interface DayMerchantRow {
  key: string;
  display_name: string;
  post_count: number;
  total_views: number;
  total_reactions: number;
  total_forwards: number;
  total_engagement: number;
  engagement_rate: number | null;
  deal_count: number;
  type_dist: Record<string, number>;
  top_post: { views: number; preview: string } | null;
}

export interface DayBaseline {
  avg_posts_per_day: number;
  avg_views_per_post: number;
  window: string;
}

export type DayResponse =
  | { date: string | null; available: false; note: string }
  | {
      date: string;
      available: true;
      posts: number;
      total_views: number;
      avg_views_per_post: number;
      merchants: DayMerchantRow[];
      type_mix: [string, number][];
      merchant_mix: [string, number][];
      baseline: DayBaseline;
      vs_baseline: { posts_delta: number; views_delta_pct: number | null };
    };

// ---------------------------------------------------------------------------
// GET /api/drafts
// ---------------------------------------------------------------------------

export interface WhyThisDeal {
  rank_score: number | null;
  merchant: string | null;
  discount_percent: number | null;
  score_breakdown: Record<string, unknown> | null;
  why: string;
  deal_count?: number;
}

export interface StrategyRationale {
  kind: string;
  period: string;
  emoji_policy: EmojiPolicy;
  target_window_ist?: {
    part: string;
    hours: string;
    avg_views_per_day: number;
    why: string;
  };
  why_type?: string;
  why_this_deal?: WhyThisDeal;
  note?: string;
}

export interface DraftItem {
  id: number;
  post_type: string;
  status: string;
  bucket: string | null;
  rank_score: number | null;
  text: string;
  affiliate_status: string | null;
  // format_meta's own emoji_policy — the formatter's shape, distinct from
  // (but overlapping with) StrategyRationale.emoji_policy; the page falls
  // back between the two.
  emoji_policy: Partial<EmojiPolicy> | null;
  rationale: StrategyRationale | null;
  generated_at: string | null;
}

export interface DraftsResponse extends PageMeta {
  items: DraftItem[];
}

// ---------------------------------------------------------------------------
// GET /api/posts
// ---------------------------------------------------------------------------

export interface PostItem {
  id: number;
  posted_at: string | null;
  views: number | null;
  forwards: number | null;
  preview: string;
  links: string[];
}

export interface PostsResponse extends PageMeta {
  items: PostItem[];
}

// ---------------------------------------------------------------------------
// GET /api/queue
// ---------------------------------------------------------------------------

export interface QueueItem {
  id: number;
  post_id: number | null;
  channel: string | null;
  category: string | null;
  status: string;
  scheduled_at: string | null;
  attempts: string;
  note: string;
}

export interface QueueResponse extends PageMeta {
  counts: Record<string, number>;
  items: QueueItem[];
}

// ---------------------------------------------------------------------------
// GET /api/competitors, GET /api/competitor-dashboard
// ---------------------------------------------------------------------------

export interface CompetitorBenchmarkRow {
  dimension: string;
  owned_value: number | null;
  competitor_value: number | null;
  delta: number | null;
}

export interface CompetitorEntity {
  name: string;
  is_owned?: boolean;
  category?: "platform" | "channel" | "unclassified";
  posts_per_day?: number | null;
  avg_views_per_post?: number | null;
  emoji_rate?: number | null;
  cta_rate?: number | null;
  coupon_rate?: number | null;
  hashtag_rate?: number | null;
  media_rate?: number | null;
  avg_links?: number | null;
  deal_mix?: Record<string, number>;
  merchant_mix?: Record<string, number>;
  similarity_to_us?: number | null;
  benchmarks?: CompetitorBenchmarkRow[];
  posts_per_hour_ist?: Record<string, number>;
  weekday_distribution?: Record<string, number>;
  posts?: number;
  tenure_label?: string;
  // Comparison entities carry many more loosely-typed dimensions accessed
  // dynamically by key (see CompetitorDashboard.tsx's STYLE_DIMS) — `any`
  // here (not `unknown`) is deliberate so that dynamic `e[dim.key]` access
  // stays usable without a cast at every call site.
  [key: string]: any;
}

export interface CompetitorSignalDTO {
  type: "threat" | "opportunity";
  competitor: string;
  kind: string;
  description: string;
  confidence: number;
}

export interface CompetitorsResponse {
  profiles: CompetitorEntity[];
  signals: CompetitorSignalDTO[];
}

export interface CompetitorDashboardResponse {
  summary: { total: number; platform: number; channel: number; signals: number };
  platform: CompetitorEntity[];
  channel: CompetitorEntity[];
  signals: CompetitorSignalDTO[];
  unavailable: string[];
  note: string;
  metrics: string[];
  applied_window: number | null;
}

// ---------------------------------------------------------------------------
// GET /api/merchants
// ---------------------------------------------------------------------------

export interface MerchantProfileDTO {
  merchant: string;
  posts: number;
  avg_views_per_day: number | null;
  price_median: number | null;
  confidence: number;
}

export interface MerchantOpportunityDTO {
  merchant: string;
  kind: string;
  description: string;
  confidence: number;
}

export interface MerchantsResponse {
  profiles: MerchantProfileDTO[];
  opportunities: MerchantOpportunityDTO[];
}

// ---------------------------------------------------------------------------
// GET /api/plans, GET /api/weekly
// ---------------------------------------------------------------------------

export interface CampaignPlanDTO {
  plan_type: "daily" | "weekly" | "event" | string;
  title: string;
  target_date: string | null;
  confidence: number;
  blueprint: Record<string, unknown>;
  // shape varies by plan_type (e.g. { estimated_daily_views } for daily plans) —
  // unlike GrowthRecommendation.expected_outcome, which is a plain string.
  expected_outcome: Record<string, unknown> | null;
  risks: { detail: string; [key: string]: unknown }[] | null;
}

export type PlansResponse = CampaignPlanDTO[];

export interface WeeklyResponse {
  available: boolean;
  weekly_plan: {
    title: string;
    blueprint: Record<string, unknown>;
    expected_outcome: string | null;
    confidence: number;
    generated_at: string | null;
  } | null;
  what_changed: ReasonedInsightDTO[];
  recommendations: GrowthRecommendation[];
  ai_summary: string | null;
}

// ---------------------------------------------------------------------------
// Org / Channels / Users (Settings.tsx)
// ---------------------------------------------------------------------------

export interface OrgSettings {
  grabon_shortener_url?: string;
  grabon_amazon_tag?: string;
  grabon_flipkart_params?: string;
  grabon_shorten_all?: boolean;
  preferred_categories?: string[];
  [key: string]: unknown;
}

export interface OrgResponse {
  id: number;
  key: string;
  name: string;
  affiliate_provider: string;
  settings: OrgSettings;
  channels: number;
}

export interface ChannelDTO {
  id: number;
  username: string | null;
  title: string | null;
  kind: "owned" | "competitor";
  status: "pending" | "active" | string;
  resolved: boolean;
  org_id: number | null;
  posts: number;
}

export interface UserAccount {
  id: number;
  org_id: number;
  name: string;
  email: string | null;
  role: "owner" | "editor" | "viewer";
  has_password: boolean;
  last_login_at: string | null;
}

export type UsersResponse = UserAccount[];
export type ChannelsResponse = ChannelDTO[];

// ---------------------------------------------------------------------------
// Auth (providers/auth.tsx also declares `User` — kept as an alias so existing
// imports of `User` from there keep working; the canonical shape lives here)
// ---------------------------------------------------------------------------

export interface AuthUser {
  id: number;
  org_id: number;
  name: string;
  email: string | null;
  role: "owner" | "editor" | "viewer";
}

export interface LoginResponse {
  token: string;
  user: AuthUser;
}
