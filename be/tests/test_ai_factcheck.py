from src.ai.factcheck import check_cited_numbers


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
