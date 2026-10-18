"""Briefings produced during this session, so the chat can discuss them."""
from . import workbook

_briefings = {}


def remember(briefing):
    _briefings[(workbook.current().sha, briefing["ticker"].upper())] = briefing


def get(ticker):
    return _briefings.get((workbook.current().sha, str(ticker).upper()))


def tickers():
    sha = workbook.current().sha
    return sorted(t for (s, t) in _briefings if s == sha)
