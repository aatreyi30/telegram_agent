from src.services.analytics.reconciliation import compute_adherence


def test_adherence_counts_and_missed_windows():
    plan_slots = [
        {"type": "single", "window_ist": "12:00-13:00", "theme": "electronics"},
        {"type": "collection", "window_ist": "19:00-20:00", "theme": "fashion"},
        {"type": "single", "window_ist": "21:00-22:00", "theme": "home"},
    ]
    published = [
        {"type": "single", "hour_ist": 12},
        {"type": "collection", "hour_ist": 19},
    ]
    res = compute_adherence(plan_slots, published)
    assert res["planned"] == 3
    assert res["published"] == 2
    assert res["matched"] == 2
    assert "21:00-22:00" in res["missed_windows"]
