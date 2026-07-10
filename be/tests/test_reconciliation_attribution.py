from src.services.analytics.reconciliation import compute_attribution


def test_attribution_diffs_predictions():
    expected = {"electronics_views_pct": 15}
    report = {"electronics_views_pct": 3}
    res = compute_attribution(expected, report)
    item = res["items"][0]
    assert item["metric"] == "electronics_views_pct"
    assert item["expected"] == 15
    assert item["actual"] == 3
    assert res["correlational"] is True
