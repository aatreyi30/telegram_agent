from src.ai.factcheck import check_cited_numbers, extract_prose_numbers


def _reports():
    return [{"views_total": 2100, "forwards_total": 980, "engagement_rate": 0.30, "views_max": 4000}]


def test_all_cited_numbers_present_passes():
    res = check_cited_numbers([2100, 980, 0.30], _reports())
    assert res["status"] == "passed"
    assert res["unverified"] == []


def test_fabricated_number_fails():
    res = check_cited_numbers([2100, 9999], _reports())
    assert res["status"] == "failed"
    assert 9999 in res["unverified"]


def test_minor_unverified_warns_not_fails():
    # 1 of 5 cited (20%) unverified — e.g. a stray hour label like 23 — is a WARN,
    # not a hard fail: the plan is still mostly-grounded and safe to act on.
    res = check_cited_numbers([2100, 980, 0.30, 4000, 23], _reports())
    assert res["status"] == "warn"
    assert 23 in res["unverified"]


def test_majority_unverified_still_fails():
    # 3 of 4 unverified (75%) — substantial fabrication — must fail.
    res = check_cited_numbers([2100, 111, 222, 333], _reports())
    assert res["status"] == "failed"


def test_prose_date_years_are_never_extracted_as_cited_numbers():
    """Regression: the system prompt REQUIRES the digest to name a specific day (e.g.
    'the strongest day was 2026-07-23'). Extracting the YEAR from that date as a
    'cited number' meant it almost never matched anything in the report pool (no real
    metric is ever exactly '2026') and could fail an otherwise fully-grounded weekly
    narrative for citing nothing but the date the prompt told it to cite. A year is
    never a real metric — must be dropped, whichever way it's written."""
    plan_iso = {"digest": "The strongest day was 2026-07-23 with 42 posts and 20320 views."}
    nums = extract_prose_numbers(plan_iso)
    assert 2026 not in nums
    assert 42 in nums and 20320 in nums   # real metrics still extracted normally

    plan_written = {"digest": "This week started on August 9, 2026 with no posts yet."}
    nums2 = extract_prose_numbers(plan_written)
    assert 2026 not in nums2
    assert 9 in nums2   # the day-of-month is a plain number, not a year — still extracted

    # A genuinely cited metric that happens to be 4 digits but NOT in the 2000-2099
    # "looks like a year" band must still be extracted normally.
    plan_real_metric = {"digest": "Total views this week reached 15234, a new high."}
    assert 15234 in extract_prose_numbers(plan_real_metric)
