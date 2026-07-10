"""AI daily / weekly growth briefing.

Turns the verified engine outputs (reasoning, growth recs, merchant
opportunities) into the operator's plain-language morning briefing.
Grounded: the model only narrates the data bundle it is given.  Falls back to
a local template-based narrative when the AI API is unavailable or rate-limited.
"""

from __future__ import annotations

from src.ai.client import AIClient, AIUnavailable
from src.ai.context import full_briefing_context, to_json
from src.ai.prompts import DAILY_INSTRUCTIONS as _DAILY_INSTRUCTIONS
from src.ai.prompts import WEEKLY_INSTRUCTIONS as _WEEKLY_INSTRUCTIONS
from src.db.session import session_scope


class BriefingGenerator:
    def __init__(self) -> None:
        self.ai = AIClient()

    def generate(self, weekly: bool = False) -> str:
        with session_scope() as s:
            ctx = full_briefing_context(s, weekly=weekly)
        if not ctx["channel"].get("available"):
            return "No channel data yet — run collection and the intelligence engines first."
        try:
            instructions = _WEEKLY_INSTRUCTIONS if weekly else _DAILY_INSTRUCTIONS
            user = f"{instructions}\n\nDATA:\n{to_json(ctx)}"
            return self.ai.complete(user, max_tokens=1500, effort="medium")
        except AIUnavailable:
            pass
        return self._fallback(ctx, weekly)

    @staticmethod
    def _pick(recs: list[dict], *categories: str) -> list[dict]:
        return [r for r in recs if r.get("category") in categories]

    def _fallback(self, ctx: dict, weekly: bool) -> str:
        lines: list[str] = []
        if weekly:
            self._fallback_weekly(ctx, lines)
        else:
            self._fallback_daily(ctx, lines)
        return "\n".join(lines)

    def _fallback_weekly(self, ctx: dict, lines: list[str]) -> None:
        ch = ctx.get("channel", {})
        sub = ch.get("subscribers")
        ch_name = ch.get("title") or ch.get("username") or "channel"
        lines.append(f"Weekly summary for {ch_name}"
                     + (f" ({sub:,} subscribers)" if sub else ""))

        pt = ctx.get("post_type_performance", [])
        best = pt[0] if pt else None
        if best:
            lines.append(f"Biggest win: {self._type_label(best['post_type'])} posts "
                         f"averaged {best['avg_views_per_day']:.0f} views/day "
                         f"({best['posts']} posts, {best['share']*100:.0f}% of volume).")
            if len(pt) > 1:
                worst = pt[-1]
                if worst["share"] >= 0.1:
                    lines.append(f"Biggest concern: {self._type_label(worst['post_type'])} "
                                 f"averaged only {worst['avg_views_per_day']:.0f} views/day "
                                 f"yet are {worst['share']*100:.0f}% of posts.")

        recs = ctx.get("growth_recommendations", [])
        if recs:
            lines.append("\nWhat to change next week:")
            for r in self._pick(recs, "post_type", "frequency", "diversity", "timing")[:3]:
                lines.append(f"  * {r['recommendation']}")

    def _fallback_daily(self, ctx: dict, lines: list[str]) -> None:
        ch = ctx.get("channel", {})
        sub = ch.get("subscribers")
        ch_name = ch.get("title") or ch.get("username") or "channel"
        lines.append(f"Daily briefing for {ch_name}"
                     + (f" ({sub:,} subscribers)" if sub else ""))

        wi = ctx.get("what_changed_and_why", [])
        if wi:
            lines.append("\nWhat changed & why:")
            for w in wi[:3]:
                lines.append(f"  * {w.get('observation', '')}")

        recs = ctx.get("growth_recommendations", [])
        if recs:
            lines.append("\nDo today:")
            for r in recs[:3]:
                lines.append(f"  * {r['recommendation']}")

    @staticmethod
    def _type_label(pt: str) -> str:
        if pt == "loot_deal":
            return "loot / multi-deal"
        if pt == "single_deal":
            return "single deal"
        return pt or "posts"
