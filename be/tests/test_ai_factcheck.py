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
