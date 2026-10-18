"""The app's view of the workbook must agree with an independent read of the Excel file."""
from statistics import mean

import pytest

from app import workbook
from tests.conftest import MISSING_TICKERS, file_hash

COLS = {"d1": "Daily Perf.", "m3": "3M Perf.", "m6": "6M Perf.", "y1": "1Y Perf."}


def expected_signal(points):
    return "Positive" if points >= 20 else "Negative" if points <= -10 else "Mixed"


def test_every_field_of_every_row_matches(raw):
    app_rows = workbook.rows()
    assert len(app_rows) == len(raw) == 50
    for a, r in zip(app_rows, raw):
        assert (a["id"], a["company"], a["ticker"], a["index"], a["sector"], a["canton"]) == (
            r["Security ID"], r["Company"], r["Ticker"], r["Index"], r["Sector"], r["Canton"])
        assert a["price"] == r["Price (CHF)"] and a["isin"] == r["ISIN"] and a["source_url"] == r["Source URL"]
        for key, col in COLS.items():
            expected = None if r[col] is None else pytest.approx(r[col] * 100, abs=0.006)
            assert a[key] == expected, (a["ticker"], key)


def test_momentum_points_equal_excel_score_times_100(raw):
    for a, r in zip(workbook.rows(), raw):
        if r["Momentum Score"] is None:
            assert a["score"] is None
        else:
            assert a["score"] == pytest.approx(r["Momentum Score"] * 100, abs=0.01), a["ticker"]


def test_workbook_signal_is_carried_over_unchanged(raw):
    assert [a["signal_workbook"] for a in workbook.rows()] == [r["Signal"] for r in raw]


def test_corrected_signals_use_the_intended_thresholds(raw_complete):
    expected = {r["Ticker"]: expected_signal(r["Momentum Score"] * 100) for r in raw_complete}
    for a in workbook.rows():
        assert a["signal"] == expected.get(a["ticker"], "Data missing"), a["ticker"]
    counts = {s: list(expected.values()).count(s) for s in ("Positive", "Mixed", "Negative")}
    assert counts == {"Positive": 8, "Mixed": 33, "Negative": 3}
    k = workbook.summary()["kpis"]
    assert (k["positive"], k["mixed"], k["negative"]) == (8, 33, 3)
    assert (k["wb_positive"], k["wb_mixed"], k["wb_negative"]) == (0, 44, 0)


def test_expected_positive_and_negative_names(raw_complete):
    pos = {r["Ticker"] for r in raw_complete if r["Momentum Score"] * 100 >= 20}
    neg = {r["Ticker"] for r in raw_complete if r["Momentum Score"] * 100 <= -10}
    assert pos == {"VACN", "CLN", "UBSG", "CFR", "KNIN", "ABBN", "BAER", "RO"}
    assert neg == {"PGHN", "LISN", "LISP"}


def test_kpis_match_the_management_summary(wb_values):
    k = workbook.summary()["kpis"]
    s = {r[0]: r[1] for r in wb_values["Management Summary"].iter_rows(min_row=4, max_row=10, values_only=True)}
    assert k["securities"] == s["Securities"] == 50
    assert k["complete"] == s["With complete market snapshot"] == 44
    assert k["avg_m3"] == pytest.approx(s["Average 3M performance"] * 100, abs=0.006)
    assert k["avg_m6"] == pytest.approx(s["Average 6M performance"] * 100, abs=0.006)
    assert k["avg_y1"] == pytest.approx(s["Average 1Y performance"] * 100, abs=0.006)


def test_missing_data_is_excluded_not_zero(raw, raw_complete):
    for a in workbook.rows():
        if a["ticker"] in MISSING_TICKERS:
            assert a["complete"] is False and a["score"] is None and a["signal"] == "Data missing"
            assert a["m3"] is None and a["y1"] is None
    k = workbook.summary()["kpis"]
    with_zeros = mean([(r["3M Perf."] or 0) * 100 for r in raw])
    assert k["avg_m3"] != pytest.approx(with_zeros, abs=0.5)
    assert k["avg_m3"] == pytest.approx(mean(r["3M Perf."] for r in raw_complete) * 100, abs=0.006)


def test_sector_statistics(sector_groups):
    stats = {s["sector"]: s for s in workbook.sector_stats()}
    assert set(stats) == set(sector_groups) and sum(s["n"] for s in stats.values()) == 50
    for sector, items in sector_groups.items():
        s = stats[sector]
        assert s["n_complete"] == len(items)
        assert s["avg_m3"] == pytest.approx(mean(r["3M Perf."] for r in items) * 100, abs=0.006)
        assert s["avg_y1"] == pytest.approx(mean(r["1Y Perf."] for r in items) * 100, abs=0.006)
        assert s["avg_score"] == pytest.approx(mean(r["Momentum Score"] for r in items) * 100, abs=0.01)


def test_best_sector_by_one_year_and_by_momentum(sector_groups):
    by_y1 = max(sector_groups, key=lambda s: mean(r["1Y Perf."] for r in sector_groups[s]))
    by_score = max(sector_groups, key=lambda s: mean(r["Momentum Score"] for r in sector_groups[s]))
    assert by_y1 == by_score == "Materials"
    assert workbook.sector_stats()[0]["sector"] == "Materials"


def test_share_classes_and_distinct_companies(raw):
    k = workbook.summary()["kpis"]
    assert k["distinct_companies"] == len({r["Company"] for r in raw}) == 47
    classes = {a["company"]: a["share_classes"] for a in workbook.rows() if len(a["share_classes"]) > 1}
    assert classes == {"Roche Holding AG": ["RO", "ROP"], "Schindler Holding Ltd": ["SCHN", "SCHP"],
                       "Chocoladefabriken Lindt & Sprüngli AG": ["LISN", "LISP"]}


def test_findings_describe_the_workbook_correctly():
    f = {x["key"]: x for x in workbook.findings()}
    assert set(f) == {"scale", "missing", "share_classes", "stale"}
    assert f["scale"]["counts"]["positive"] == 8 and f["scale"]["counts"]["wb_mixed"] == 44
    assert set(f["missing"]["tickers"]) == MISSING_TICKERS
    assert "47 distinct" in f["share_classes"]["action"]


def test_llm_context_table_is_faithful(raw):
    corrected = workbook.llm_context_table(corrected=True).splitlines()
    original = workbook.llm_context_table(corrected=False).splitlines()
    assert len(corrected) == len(original) == 51
    assert sum(l.endswith("| Positive") for l in corrected) == 8
    assert sum(l.endswith("| Positive") for l in original) == 0
    assert sum(l.endswith("| Mixed") for l in original) == 44
    for line in corrected[1:]:
        cells = [c.strip() for c in line.split("|")]
        if cells[1] in MISSING_TICKERS:
            assert cells[4:10] == ["n/a"] * 6, line
    vat = next(l for l in corrected if "| VACN |" in l)
    assert "603.2" in vat


def test_demo_prompts_are_loaded():
    prompts = workbook.demo_prompts()
    assert len(prompts) == 10 and prompts[-1]["tool"] == "Foundry"


def test_reading_the_workbook_never_changes_the_file():
    before = file_hash()
    workbook.summary(), workbook.findings(), workbook.sector_stats(), workbook.llm_context_table()
    assert file_hash() == before
