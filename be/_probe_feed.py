import collections
from src.services.generation.deal_source import DealSourceClient
c = DealSourceClient()
ok, reason = c.available()
print("available:", ok, reason)
raw = c._collect_raw(want=300, page_size=80)
print("total raw items:", len(raw))
tally = collections.Counter((str(it.get("retailer_key") or it.get("merchant_key") or "?")).lower() for it in raw)
for m, n in tally.most_common():
    print(f"  {m:20s} {n}")
