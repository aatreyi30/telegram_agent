// Shared display formatting: turn the backend's raw slugs/enums/ISO timestamps into
// language a marketing operator reads without a decoder ring. Every page funnels its
// labels/times/money through here, so "aislot:5:1:0", "blocked_stale", "nykaa_fashion"
// and UTC ISO strings never reach the screen.

import { formatDistanceToNowStrict, parseISO } from "date-fns";

/* ---------- generic slug -> Title Case ---------- */

const SMALL = new Set(["and", "or", "the", "a", "an", "of", "for", "to", "in"]);

/** "electronics-and-gadgets" -> "Electronics & Gadgets"; "nykaa_fashion" -> "Nykaa Fashion". */
export function titleCase(slug?: string | null): string {
  if (!slug) return "";
  return String(slug)
    .replace(/[-_]+/g, " ")
    .trim()
    .split(/\s+/)
    .map((w, i) => (w === "and" && i > 0 ? "&" : SMALL.has(w) && i > 0 ? w : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");
}

/* ---------- merchants ---------- */

// Only special-casing where Title Case gets the branding wrong. Everything else
// (ajio -> "Ajio", shopsy -> "Shopsy", nykaa_fashion -> "Nykaa Fashion") is handled
// by titleCase, so unknown/new merchants still render cleanly.
const MERCHANT: Record<string, string> = {
  amazon: "Amazon", amazon_in: "Amazon", flipkart: "Flipkart", myntra: "Myntra",
  ajio: "AJIO", tatacliq: "Tata CLiQ", nykaa: "Nykaa", nykaa_fashion: "Nykaa Fashion",
  jiomart: "JioMart", bigbasket: "BigBasket", firstcry: "FirstCry", boat: "boAt",
  hm: "H&M", thebodyshop: "The Body Shop", bookmyshow: "BookMyShow",
};

export function merchantLabel(key?: string | null): string {
  if (!key) return "Mixed";
  return MERCHANT[String(key).toLowerCase()] ?? titleCase(key);
}

/** "@rival" for a handle, or a fallback ("this channel") when there's no username. */
export function atOr(username?: string | null, fallback = "this account"): string {
  return username ? `@${username}` : fallback;
}

// Merchants GrabOn actually earns a commission on (real affiliate rule in
// affiliate/grabon.py). Everything else only gets its link shortened — no payout.
export const EARNING_MERCHANTS = new Set(["amazon", "amazon_in", "flipkart"]);

/* ---------- post / deal types ---------- */

const POST_TYPE: Record<string, string> = {
  single_deal: "Single deal", single: "Single deal", deal: "Single deal",
  loot_deal: "Loot board", loot: "Loot board", collection: "Loot board",
  category: "Category board", category_collection: "Category board",
  manual: "Manual", mixed: "Mixed",
};

export function postTypeLabel(key?: string | null): string {
  if (!key) return "—";
  return POST_TYPE[String(key).toLowerCase()] ?? titleCase(key);
}

export function categoryLabel(key?: string | null): string {
  if (!key) return "";
  return titleCase(key);
}

/* ---------- statuses (label + colour tone) ---------- */

export type Tone = "default" | "success" | "warning" | "destructive" | "secondary";

// Maps every queue/post/job status the backend emits to a plain word + a tone that
// matches the app's Badge variants. Unknown statuses fall back to Title Case + neutral.
const STATUS: Record<string, { label: string; tone: Tone }> = {
  queued: { label: "Queued", tone: "default" },
  scheduled: { label: "Queued", tone: "default" },
  pending: { label: "Waiting", tone: "warning" },
  sent: { label: "Published", tone: "success" },
  published: { label: "Published", tone: "success" },
  success: { label: "OK", tone: "success" },
  active: { label: "Active", tone: "success" },
  failed: { label: "Failed", tone: "destructive" },
  error: { label: "Failed", tone: "destructive" },
  blocked: { label: "Blocked", tone: "warning" },
  blocked_stale: { label: "Stale link", tone: "warning" },
  skipped: { label: "Skipped", tone: "secondary" },
  draft: { label: "Draft", tone: "secondary" },
  retrying: { label: "Retrying", tone: "warning" },
  limited: { label: "Rate-limited", tone: "warning" },
  never: { label: "Never run", tone: "secondary" },
  "never run": { label: "Never run", tone: "secondary" },
};

export function statusLabel(key?: string | null): string {
  if (!key) return "—";
  return STATUS[String(key).toLowerCase()]?.label ?? titleCase(key);
}

export function statusTone(key?: string | null): Tone {
  if (!key) return "secondary";
  return STATUS[String(key).toLowerCase()]?.tone ?? "secondary";
}

/* ---------- affiliate / money ---------- */

export interface MoneyChip { label: string; tone: Tone; hint: string }

/**
 * Honest earnings signal for a post. The backend stamps `grabon_applied` on EVERY
 * post that ran through the provider — but for AJIO/Myntra/etc. there's no real
 * affiliate rule, so the link is merely shortened and earns ₹0. Don't show a green
 * "affiliate links" badge for those; that's the lie the old UI told.
 */
export function moneyChip(affiliateStatus?: string | null, merchant?: string | null): MoneyChip {
  const m = (merchant || "").toLowerCase();
  const applied = !!affiliateStatus && affiliateStatus.endsWith("_applied");
  if (applied && EARNING_MERCHANTS.has(m)) {
    return { label: "Earns", tone: "success", hint: `Affiliate link — commission on ${merchantLabel(merchant)}` };
  }
  if (applied) {
    return { label: "Shortened only", tone: "warning", hint: `No affiliate payout for ${merchantLabel(merchant)} — link is only shortened` };
  }
  return { label: "Clean link", tone: "secondary", hint: "No affiliate provider — plain product link" };
}

/* ---------- time (always IST, no matter the viewer's timezone) ---------- */

const IST = "Asia/Kolkata";
const _date = new Intl.DateTimeFormat("en-IN", { timeZone: IST, day: "numeric", month: "short" });
const _dateTime = new Intl.DateTimeFormat("en-IN", { timeZone: IST, day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true });

function _parse(iso?: string | null): Date | null {
  if (!iso) return null;
  // The backend sends naive UTC ISO strings (no 'Z'/offset). date-fns parseISO would
  // read a timezone-less string as the VIEWER's local time — off by their UTC offset.
  // Append 'Z' when there's no timezone marker so it's correctly read as UTC, then
  // istDate/istDateTime/relative convert to IST properly.
  const s = /([Zz]|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : iso + "Z";
  const d = parseISO(s);
  return isNaN(d.getTime()) ? null : d;
}

export function istDate(iso?: string | null): string { const d = _parse(iso); return d ? _date.format(d) : "—"; }
export function istDateTime(iso?: string | null): string { const d = _parse(iso); return d ? _dateTime.format(d) : "—"; }

/** "fires in 12 min" / "5 min ago". Null-safe. */
export function relative(iso?: string | null): string {
  const d = _parse(iso);
  if (!d) return "—";
  const future = d.getTime() > Date.now();
  const dist = formatDistanceToNowStrict(d, { addSuffix: false });
  return future ? `in ${dist}` : `${dist} ago`;
}
