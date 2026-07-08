"""Post-copy instructions, consumed by `src.ai.copywriter.Copywriter`."""

from __future__ import annotations

COPYWRITER_INSTRUCTIONS = (
    "Write ONE short Telegram deal post for this channel, using ONLY the PRODUCT facts "
    "and matching the channel's STYLE.\n"
    "Rules:\n"
    "- Use only the product title, prices, discount, coupon, and link that are given. "
    "Never invent a price, feature, spec, or claim.\n"
    "- Lead with the product; show the current price and discount if present; include the "
    "link exactly as given.\n"
    "- Use the channel's high-performing emojis sparingly; keep the caption near the "
    "channel's typical length.\n"
    "- If a field is missing, simply omit it — do not fill it in.\n"
    "Return only the post text — no explanation."
)
