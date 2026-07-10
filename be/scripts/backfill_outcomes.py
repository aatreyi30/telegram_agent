"""One-time bootstrap (Phase 2.2): seed `post_outcomes` for owned posts already
older than 24h, using their LATEST observed counters directly on `posts`
(views/forwards/reactions_total) rather than `post_metric_snapshots` -- the
per-horizon snapshot time series is new, so these older posts were never
captured at exact 1h/6h/24h offsets. This gives baseline_v1 a full 28 days of
`engagement_score` history on day one, instead of waiting weeks for the
regular OutcomeCollector to build it up post-by-post going forward.

Only the 24h phase is marked done (that's the horizon these "latest counters"
approximate); 1h/6h are left not-done/null -- those exact early windows are
gone for good on posts this old, and the regular OutcomeCollector job never
retries them because we only re-check un-25h-done rows.

Usage:
    cd be
    python -m scripts.backfill_outcomes
"""

import sys

sys.path.insert(0, "src")

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.db.models import Channel, Post
from src.db.models_prediction import PostOutcome
from src.db.session import session_scope
from src.services.analytics.engagement import channel_distribution, engagement_score


def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    created = skipped = 0
    dist_cache: dict[int, dict] = {}

    with session_scope() as s:
        posts = s.execute(
            select(Post.id, Post.channel_id, Post.views, Post.forwards, Post.reactions_total)
            .join(Channel, Channel.id == Post.channel_id)
            .where(Channel.kind == "owned", Post.posted_at.isnot(None), Post.posted_at <= cutoff)
        ).all()
        existing_ids = {o.post_id for o in s.scalars(select(PostOutcome))}

        for pid, channel_id, views, forwards, reactions in posts:
            if pid in existing_ids:
                skipped += 1
                continue

            views = views or 0
            forwards = forwards or 0
            reactions = reactions or 0
            forward_rate = forwards / max(views, 1)
            reaction_rate = reactions / max(views, 1)

            if channel_id not in dist_cache:
                dist_cache[channel_id] = channel_distribution(s, channel_id)
            score = engagement_score(views, forward_rate, reaction_rate, dist_cache[channel_id])

            s.add(
                PostOutcome(
                    post_id=pid,
                    views_24h=views,
                    forwards_24h=forwards,
                    reactions_24h=reactions,
                    forward_rate=forward_rate,
                    reaction_rate=reaction_rate,
                    engagement_score=score,
                    phase_1h_done=False,
                    phase_6h_done=False,
                    phase_24h_done=True,
                )
            )
            created += 1

        if created:
            s.flush()

    print(
        f"backfill_outcomes: created {created} outcome row(s), "
        f"skipped {skipped} (already had one)."
    )


if __name__ == "__main__":
    main()
