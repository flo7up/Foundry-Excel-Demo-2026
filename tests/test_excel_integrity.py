"""Facts about the Excel file itself, checked without any app code."""
import re

import pytest

from tests.conftest import MISSING_TICKERS

PERF = ["Daily Perf.", "3M Perf.", "6M Perf.", "1Y Perf."]


def test_expected_sheets(wb_values):
    assert wb_values.sheetnames == ["SMI Expanded Portfolio", "Management Summary", "Demo Prompts", "Sources & Limitations"]


def test_fifty_unique_securities(raw):
    assert len(raw) == 50
    assert [r["Security ID"] for r in raw] == [f"SEC-{i:03d}" for i in range(1, 51)]
    assert len({r["Ticker"] for r in raw}) == 50


def test_six_securities_have_no_market_data(raw):
    missing = {r["Ticker"] for r in raw if r["Price (CHF)"] is None}
    assert missing == MISSING_TICKERS


def test_missing_rows_are_blank_not_zero(raw):
    for r in raw:
        if r["Ticker"] in MISSING_TICKERS:
            assert all(r[c] is None for c in PERF), r["Company"]
            assert r["Data Coverage"] == "Constituent metadata only"
            assert r["Signal"] == "Data missing"


def test_complete_rows_are_fully_populated_and_plausible(raw_complete):
    assert len(raw_complete) == 44
    for r in raw_complete:
        assert r["Price (CHF)"] > 0, r["Company"]
        assert all(r[c] is not None for c in PERF), r["Company"]
        assert -1 < r["1Y Perf."] < 5 and -1 < r["Daily Perf."] < 1, r["Company"]
        assert r["Data Coverage"] == "Complete market snapshot"
        assert r["Market Data Date"] == "28.08.2026"
        assert re.fullmatch(r"CH\d{10}", r["ISIN"]), (r["Company"], r["ISIN"])


def test_isins_are_unique(raw_complete):
    isins = [r["ISIN"] for r in raw_complete]
    assert len(isins) == len(set(isins))


def test_every_row_has_an_https_source(raw):
    assert all(str(r["Source URL"]).startswith("https://") for r in raw)


def test_momentum_formula_weights(wb_formulas):
    ws = wb_formulas["SMI Expanded Portfolio"]
    for row in range(2, 52):
        f = ws.cell(row=row, column=13).value
        assert f == f'=IF(COUNT(I{row}:L{row})=0,"",I{row}*0.05+J{row}*0.2+K{row}*0.3+L{row}*0.45)', row


def test_cached_momentum_matches_weights(raw_complete):
    for r in raw_complete:
        p = [r[c] for c in PERF]
        assert r["Momentum Score"] == pytest.approx(p[0] * 0.05 + p[1] * 0.2 + p[2] * 0.3 + p[3] * 0.45, abs=1e-9), r["Company"]


def test_known_defect_signal_scale(wb_formulas, raw_complete, wb_values):
    """Characterisation test: the workbook's own Signal column can never leave 'Mixed'.

    Momentum is a decimal fraction (about 0.12) while the thresholds are 20 and -10.
    If someone fixes the workbook, this test should be updated on purpose.
    """
    ws = wb_formulas["SMI Expanded Portfolio"]
    assert ">=20" in ws["N2"].value and "<=-10" in ws["N2"].value
    scores = [r["Momentum Score"] for r in raw_complete]
    assert max(scores) < 20 and min(scores) > -10
    assert {r["Signal"] for r in raw_complete} == {"Mixed"}
    summary = {r[0]: r[1] for r in wb_values["Management Summary"].iter_rows(min_row=4, max_row=10, values_only=True)}
    assert summary["Positive signals"] == 0 and summary["Negative signals"] == 0


def test_management_summary_matches_raw_data(wb_values, raw, raw_complete):
    s = {r[0]: r[1] for r in wb_values["Management Summary"].iter_rows(min_row=4, max_row=10, values_only=True)}
    assert s["Securities"] == len(raw)
    assert s["With complete market snapshot"] == len(raw_complete)
    for label, col in [("Average 3M performance", "3M Perf."), ("Average 6M performance", "6M Perf."), ("Average 1Y performance", "1Y Perf.")]:
        assert s[label] == pytest.approx(sum(r[col] for r in raw_complete) / 44, abs=1e-9)


def test_demo_prompts_cover_three_stages(wb_values):
    rows = [r for r in wb_values["Demo Prompts"].iter_rows(min_row=2, values_only=True) if r[0]]
    assert len(rows) == 10
    assert {r[0][0] for r in rows} == {"1", "2", "3"}
    assert [r[1] for r in rows].count("Foundry") == 1


def test_sources_sheet_lists_urls(wb_values):
    rows = [r for r in wb_values["Sources & Limitations"].iter_rows(min_row=2, max_row=4, values_only=True)]
    assert len(rows) == 3 and all(str(r[3]).startswith("https://") for r in rows)
