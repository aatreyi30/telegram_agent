"""Tests for parse_stats_graph_json — pure parsing of Telegram's Google-charts-
style stats graph JSON (stats.getBroadcastStats's views_by_source_graph /
new_followers_by_source_graph) into (date, source_label, value) rows.

No DB/network involved; the sample payload below is hand-constructed to match
Telegram's documented graph JSON shape, not a captured real response.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from src.services.collection.util import IST, parse_stats_graph_json


def _ts_ms(y, m, d, h=0) -> int:
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


def test_parses_columns_and_names_into_rows():
    ts1 = _ts_ms(2026, 7, 1)
    ts2 = _ts_ms(2026, 7, 2)
    payload = {
        "columns": [
            ["x", ts1, ts2],
            ["y0", 120, 130],
            ["y1", 45, 50],
        ],
        "names": {"y0": "search", "y1": "channels"},
    }
    rows = parse_stats_graph_json(json.dumps(payload))

    assert len(rows) == 4
    by_label = {(d, label): v for d, label, v in rows}
    day1 = datetime.fromtimestamp(ts1 / 1000, tz=timezone.utc).astimezone(IST).date()
    day2 = datetime.fromtimestamp(ts2 / 1000, tz=timezone.utc).astimezone(IST).date()
    assert by_label[(day1, "search")] == 120
    assert by_label[(day2, "search")] == 130
    assert by_label[(day1, "channels")] == 45
    assert by_label[(day2, "channels")] == 50


def test_falls_back_to_column_id_when_name_missing():
    ts1 = _ts_ms(2026, 7, 1)
    payload = {"columns": [["x", ts1], ["y0", 7]], "names": {}}
    rows = parse_stats_graph_json(json.dumps(payload))
    assert rows == [(datetime.fromtimestamp(ts1 / 1000, tz=timezone.utc).astimezone(IST).date(), "y0", 7)]


def test_empty_or_malformed_input_yields_no_rows():
    assert parse_stats_graph_json(None) == []
    assert parse_stats_graph_json("") == []
    assert parse_stats_graph_json("not json") == []
    assert parse_stats_graph_json(json.dumps({"no": "columns here"})) == []
    assert parse_stats_graph_json(json.dumps({"columns": "not-a-list"})) == []
    assert parse_stats_graph_json(json.dumps({"columns": [["y0", 1, 2]]})) == []  # no "x" column


def test_skips_null_values_and_uneven_series():
    ts1 = _ts_ms(2026, 7, 1)
    ts2 = _ts_ms(2026, 7, 2)
    payload = {"columns": [["x", ts1, ts2], ["y0", None, 5]], "names": {"y0": "search"}}
    rows = parse_stats_graph_json(json.dumps(payload))
    assert len(rows) == 1
    d, label, value = rows[0]
    assert label == "search"
    assert value == 5
    assert isinstance(d, date)
