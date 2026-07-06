import { useMemo } from "react";
import { api } from "@/services/api";

const _WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// mock generators for data that doesn't have API endpoints yet
function mockTimeline(days: number, base: number, variance: number, labelFn?: (i: number) => string) {
  return Array.from({ length: days }, (_, i) => ({
    label: labelFn ? labelFn(i) : `Day ${i + 1}`,
    value: Math.max(0, Math.round(base + (Math.random() - 0.5) * variance)),
  }));
}

function mockWeekday(base: number) {
  return _WEEKDAYS.map(d => ({ label: d, value: Math.round(base + (Math.random() - 0.5) * base * 0.6) }));
}

function mockHour(base: number) {
  return Array.from({ length: 24 }, (_, h) => ({
    label: `${h.toString().padStart(2, "0")}:00`,
    value: Math.round(base * (h >= 8 && h <= 23 ? 0.5 + Math.random() * 0.8 : 0.1 + Math.random() * 0.2)),
  }));
}

function mockSparklines(v: number, n = 14) {
  return Array.from({ length: n }, (_, i) => ({
    value: Math.max(0, Math.round(v * (0.7 + Math.random() * 0.6) * (1 + Math.sin(i / 3) * 0.1))),
  }));
}

export function useAnalyticsData(analyticsRaw: any) {
  return useMemo(() => {
    const a = analyticsRaw || {};
    const win = a.window || {};
    const posts = a.timeline || [];
    const totalViews = a.total_views ?? 0;
    const totalPosts = a.total_posts ?? 0;
    const avgViews = totalPosts > 0 ? Math.round(totalViews / totalPosts) : 0;
    const days = win.days ?? 30++;

    // overview KPIs
    const kpis = {
      followers: { value: 12580, prev: 12100, trend: 3.8, sparkline: mockSparklines(12580, 21) },
      followerGrowth: { value: 480, prev: 420, trend: 14.3, sparkline: mockSparklines(480, 14) },
      totalViews: { value: totalViews, prev: Math.round(totalViews * 0.92), trend: 8.2, sparkline: posts.map(p => ({ value: p.total_views || p.avg_views || 0 })) },
      avgViewsPost: { value: avgViews, prev: Math.round(avgViews * 0.94), trend: 6.4, sparkline: posts.map(p => ({ value: p.avg_views || 0 })) },
      forwardRate: { value: 4.2, prev: 3.8, trend: 10.5, format: "percent" as const, sparkline: mockSparklines(42, 14) },
      engagementRate: { value: 8.7, prev: 9.1, trend: -4.4, format: "percent" as const, sparkline: mockSparklines(87, 14) },
      notifEnabled: { value: 34, prev: 31, trend: 9.7, format: "percent" as const, sparkline: mockSparklines(34, 14) },
      postingFreq: { value: 8.4, prev: 7.9, trend: 6.3, format: "decimal" as const, sparkline: mockSparklines(84, 14) },
      postsThisWeek: { value: 59, prev: 52, trend: 13.5, sparkline: mockSparklines(59, 7) },
      competitorsTracked: { value: 12, prev: 12, trend: 0, sparkline: mockSparklines(12, 7) },
    };

    // follower growth mock
    const followerTimeline = mockTimeline(90, 300, 120, (i) => {
      const d = new Date(); d.setDate(d.getDate() - 90 + i); return d.toISOString().slice(5, 10);
    });

    return { kpis, followerTimeline, win, posts, totalViews, totalPosts, avgViews, days };
  }, [analyticsRaw]);
}

export const CATEGORIES = [
  { key: "coupon", label: "Coupon" }, { key: "loot", label: "Loot" },
  { key: "electronics", label: "Electronics" }, { key: "fashion", label: "Fashion" },
  { key: "travel", label: "Travel" }, { key: "bank", label: "Bank" },
  { key: "cashback", label: "Cashback" }, { key: "food", label: "Food" },
  { key: "entertainment", label: "Entertainment" }, { key: "gaming", label: "Gaming" },
  { key: "beauty", label: "Beauty" }, { key: "others", label: "Others" },
];

export const MERCHANT_NAMES = ["Amazon", "Flipkart", "AJIO", "Myntra", "Meesho", "Nykaa", "Tata CLiQ", "Snapdeal", "Shopify", "Boat"];

export function getAlertData() {
  return [
    { type: "warning" as const, icon: "⚠", label: "Views dropped 25%", detail: "Last 7 days vs previous period", time: "2h ago" },
    { type: "success" as const, icon: "🔥", label: "New record engagement", detail: "Engagement rate hit 12.4%", time: "1d ago" },
    { type: "success" as const, icon: "📈", label: "Fastest follower growth", detail: "+580 followers this week", time: "2d ago" },
    { type: "warning" as const, icon: "⚠", label: "Posting consistency declined", detail: "Missed 3 posting slots", time: "3d ago" },
    { type: "danger" as const, icon: "⚠", label: "Notification rate decreasing", detail: "Down 2.1% this month", time: "4d ago" },
  ];
}
