"""Builds the two upload examples from the real SMI Expanded workbook (no invented values).

    python -m app.examples
"""
import openpyxl

from .config import ROOT, XLSX_PATH

OUT = ROOT / "data" / "examples"
PORTFOLIO_TICKERS = ["NOVN", "NESN", "ABBN", "UBSG", "ZURN", "HOLN", "SIKA", "GIVN", "VACN", "PGHN", "CLN", "ALC", "SOON", "ADEN"]


def _rows():
    ws = openpyxl.load_workbook(XLSX_PATH, data_only=False).worksheets[0]
    header = [c.value for c in ws[1]]
    return header, [dict(zip(header, [c.value for c in r])) for r in ws.iter_rows(min_row=2)]


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    _, rows = _rows()
    by_ticker = {r["Ticker"]: r for r in rows}

    # A German customer list with title rows and percent numbers, using prices and performance from the real workbook.
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Kunden"
    ws.append(["Kundenportfolio Schweiz - interne Auswertung"])
    ws.append(["Stand 28.08.2026"])
    ws.append([])
    ws.append(["Unternehmen", "Symbol", "Branche", "Kurs (CHF)", "Tagesperformance", "3M", "6M", "1Y", "Stand"])
    for t in PORTFOLIO_TICKERS:
        r = by_ticker[t]
        ws.append([r["Company"], t, r["Sector"], r["Price (CHF)"]] + [round(r[k] * 100, 2) for k in ("Daily Perf.", "3M Perf.", "6M Perf.", "1Y Perf.")] + [r["Market Data Date"]])
    wb.create_sheet("Notizen").append(["interne Notizen"])
    wb.save(OUT / "Kundenportfolio_Demo.xlsx")

    # Master data only: real companies without any price or performance column, so the mapping has to refuse it.
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stammdaten"
    ws.append(["Unternehmen", "Symbol", "Branche", "Kanton", "ISIN"])
    for t in PORTFOLIO_TICKERS:
        r = by_ticker[t]
        ws.append([r["Company"], t, r["Sector"], r["Canton"], r["ISIN"]])
    wb.save(OUT / "Stammdaten_ohne_Kurse.xlsx")


if __name__ == "__main__":
    build()
    print("written", *sorted(p.name for p in OUT.glob("*.xlsx")))
