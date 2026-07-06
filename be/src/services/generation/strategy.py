"""PostingStrategy — the single source of truth generation must obey.

Reads the STORED growth blueprint (Phase 7) + learnings (Phase 6) and exposes the
strategy in a form the generator/formatter can enforce:
  * which post types to prioritise (content mix), with target shares;
  * which emojis to LEAD with (positive lift) and which to AVOID (negative lift);
  * the recommended IST posting windows;
  * plain-language rationale — every figure carries its period + sample.

This is what closes the gap the operator flagged: previously the analysis said one
thing and the posts did another. Now the formatter/selector consume this object, so
a post cannot use an avoid-emoji or ignore the content mix.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.services.analytics.periods import owned_window, sample_note
from src.db.models_growth import GROWTH_VERSION, GrowthStrategy
from src.db.models_learning import LEARNING_VERSION, LearningRecord


@dataclass
class EmojiRule:
    emoji: str
    lift_pct: float          # (avg_with / baseline - 1) * 100
    avg_with: float
    baseline: float
    sample: int

    def note(self, window_desc: str) -> str:
        return (f"{self.emoji} {self.lift_pct:+.0f}% "
                f"({self.avg_with:.1f} vs {self.baseline:.1f} views/day · "
                f"{sample_note(self.sample, window_desc)}, correlational)")


@dataclass
class PostingStrategy:
    content_mix: list[dict] = field(default_factory=list)   # [{post_type,current_share,action,avg_views_per_day}]
    lead_emojis: list[str] = field(default_factory=list)
    avoid_emojis: list[str] = field(default_factory=list)
    emoji_rules: list[EmojiRule] = field(default_factory=list)
    posting_windows: list[dict] = field(default_factory=list)  # [{part,hours,recommended_posts_per_day,avg_views_per_day}]
    window_desc: str = "owned"
    available: bool = False

    # ---- construction ---- #
    @classmethod
    def load(cls, s: Session) -> "PostingStrategy":
        win = owned_window(s)
        window_desc = f"owned, last {win['months']} mo"
        strat = s.scalar(select(GrowthStrategy).where(
            GrowthStrategy.growth_version == GROWTH_VERSION))
        bp = (strat.blueprint if strat else {}) or {}

        rules: list[EmojiRule] = []
        for r in s.scalars(select(LearningRecord).where(
                LearningRecord.learning_version == LEARNING_VERSION,
                LearningRecord.category == "emoji")):
            emoji = (r.evidence or {}).get("emoji")
            base = r.comparison_value or (r.evidence or {}).get("baseline_views_per_day")
            if not emoji or not base:
                continue
            lift = (r.metric_value / base - 1) * 100 if r.metric_value is not None else 0.0
            rules.append(EmojiRule(emoji=emoji, lift_pct=lift, avg_with=r.metric_value or 0.0,
                                   baseline=base, sample=r.sample_size or 0))
        rules.sort(key=lambda x: x.lift_pct, reverse=True)

        # prefer the blueprint's emoji_strategy for the lead set (already the performers);
        # otherwise fall back to positive-lift rules. Avoid = any negative-lift emoji.
        lead = list(bp.get("emoji_strategy") or [r.emoji for r in rules if r.lift_pct > 0][:3])
        avoid = [r.emoji for r in rules if r.lift_pct < 0]

        return cls(
            content_mix=bp.get("content_mix") or [],
            lead_emojis=lead,
            avoid_emojis=avoid,
            emoji_rules=rules,
            posting_windows=bp.get("posting_plan") or [],
            window_desc=window_desc,
            available=bool(strat),
        )

    # ---- helpers the generator uses ---- #
    def increase_types(self) -> list[str]:
        return [m["post_type"] for m in self.content_mix if m.get("action") == "increase"]

    def best_window(self) -> dict | None:
        """The IST window with the highest age-normalized views/day."""
        wins = [w for w in self.posting_windows if w.get("avg_views_per_day")]
        return max(wins, key=lambda w: w["avg_views_per_day"], default=None)

    def emoji_policy(self) -> dict:
        return {
            "lead": self.lead_emojis,
            "avoid": self.avoid_emojis,
            "why": [r.note(self.window_desc) for r in self.emoji_rules],
        }

    def explain_emojis(self) -> str:
        lead = " ".join(self.lead_emojis) or "(none)"
        avoid = " ".join(self.avoid_emojis) or "(none)"
        return (f"Lead with {lead}; avoid {avoid}. Based on {self.window_desc}. "
                "Correlational — these emojis co-occur with your best/worst post types.")

    def _collection_type(self) -> dict | None:
        """The best-performing content-mix entry marked 'increase' — the type the
        strategy wants MORE of (typically multi-link loot collections)."""
        inc = [m for m in self.content_mix if m.get("action") == "increase"
               and m.get("avg_views_per_day")]
        return max(inc, key=lambda m: m["avg_views_per_day"], default=None)

    def rationale(self, kind: str, note: str | None = None) -> dict:
        """Per-draft explanation of WHY this post follows the strategy, with the
        underlying numbers + the period they cover (so it never reads as vague)."""
        win = self.best_window()
        r = {"kind": kind, "period": self.window_desc,
             "emoji_policy": self.emoji_policy()}
        if win:
            r["target_window_ist"] = {
                "part": win.get("part"), "hours": win.get("hours"),
                "avg_views_per_day": win.get("avg_views_per_day"),
                "why": (f"{win.get('part')} {win.get('hours')} is your strongest window at "
                        f"{win.get('avg_views_per_day')} views/day ({self.window_desc}).")}
        ct = self._collection_type()
        if kind == "collection" and ct:
            r["why_type"] = (f"Multi-link collection is your top-performing type at "
                             f"{ct['avg_views_per_day']:.0f} views/day ({self.window_desc}); "
                             f"currently only {ct['current_share']*100:.0f}% of posts — "
                             "strategy: increase.")
        elif kind == "single":
            r["why_type"] = ("Single-deal post. Strategy caps low-priced singles (a below-average "
                             f"type, {self.window_desc}); reserved for high-value standouts.")
        if note:
            r["note"] = note
        return r
