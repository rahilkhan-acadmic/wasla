"""
Builds data/events/index_daily.csv: daily open/high/low/close for Nifty 50,
Nifty Bank and India VIX, from NSE's own daily index files
(nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv, the
same data NSE's bhavcopy MCP serves). Used by src/event_study.py.

One file per trading day. Weekdays are tried by default; weekend dates are
tried only when an event in data/events/macro_events.json falls on one
(the Saturday 2025 and Sunday 2026 Budget sessions). A 404 means no trading
that day (holiday) and is skipped.

Incremental: dates already in the CSV are not fetched again, so re-running
after new trading days only downloads those.

Usage (from the project root):
    python data/events/fetch_index_history.py [--start 2020-12-01] [--end today]
"""

import argparse
import csv
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "index_daily.csv")
EVENTS = os.path.join(HERE, "macro_events.json")
URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv"
INDICES = {"Nifty 50": "NIFTY50", "Nifty Bank": "NIFTYBANK", "India VIX": "INDIAVIX"}
FIELDS = ["date", "index", "open", "high", "low", "close"]
UA = {"User-Agent": "Mozilla/5.0 (research script; daily index closes)"}


def parse_day(text: str, day: datetime.date) -> list[dict]:
    """Rows for our three indices from one ind_close_all file. The file's own
    'Index Date' must match the requested day (guards against NSE serving a
    different day's file). Two NSE quirks are tolerated:
      * a few files write the date month-first (06-Apr-2023's file says
        04-06-2023), so a day/month swap that matches is accepted;
      * India VIX rows with no open/high/low ('-', change 0: not published
        that day, e.g. 2021-02-12) are skipped rather than invented."""
    rows = []
    for r in csv.DictReader(text.splitlines()):
        name = (r.get("Index Name") or "").strip()
        if name not in INDICES:
            continue
        raw = r["Index Date"].strip()
        file_day = datetime.datetime.strptime(raw, "%d-%m-%Y").date()
        if file_day != day:
            try:
                swapped = datetime.datetime.strptime(raw, "%m-%d-%Y").date()
            except ValueError:
                swapped = None
            if swapped != day:
                raise ValueError(f"{day}: file says {file_day}")
        if "-" in (r["Open Index Value"].strip(), r["High Index Value"].strip(), r["Low Index Value"].strip()):
            continue
        rows.append({
            "date": day.isoformat(), "index": INDICES[name],
            "open": float(r["Open Index Value"]), "high": float(r["High Index Value"]),
            "low": float(r["Low Index Value"]), "close": float(r["Closing Index Value"]),
        })
    return rows


def wanted_days(start: datetime.date, end: datetime.date) -> list[datetime.date]:
    weekend_events = set()
    with open(EVENTS) as f:
        for e in json.load(f)["events"]:
            d = datetime.date.fromisoformat(e["date"])
            if d.weekday() >= 5:
                weekend_events.add(d)
    days, d = [], start
    while d <= end:
        if d.weekday() < 5 or d in weekend_events:
            days.append(d)
        d += datetime.timedelta(days=1)
    return days


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-12-01")
    ap.add_argument("--end", default="today")
    ap.add_argument("--delay", type=float, default=0.25, help="seconds between requests")
    a = ap.parse_args(argv)
    start = datetime.date.fromisoformat(a.start)
    end = datetime.date.today() if a.end == "today" else datetime.date.fromisoformat(a.end)

    existing = []
    if os.path.exists(OUT):
        with open(OUT) as f:
            existing = list(csv.DictReader(f))
    have = {r["date"] for r in existing}

    new, missing, errors, partial = [], 0, [], []
    for day in wanted_days(start, end):
        if day.isoformat() in have:
            continue
        try:
            req = urllib.request.Request(URL.format(d=day), headers=UA)
            text = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
            rows = parse_day(text, day)
            if len(rows) != len(INDICES):
                partial.append(f"{day}: {sorted(r['index'] for r in rows)}")
            new += rows
        except urllib.error.HTTPError as e:
            if e.code == 404:
                missing += 1  # no trading that day
            else:
                errors.append(f"{day}: HTTP {e.code}")
        except Exception as e:  # network hiccup, parse error
            errors.append(f"{day}: {type(e).__name__}: {e}")
        time.sleep(a.delay)

    all_rows = existing + [{k: (str(v) if not isinstance(v, str) else v) for k, v in r.items()} for r in new]
    all_rows.sort(key=lambda r: (r["date"], r["index"]))
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(all_rows)
    days = len({r["date"] for r in all_rows})
    print(f"{len(new)} new rows ({len(new) // len(INDICES)} days); {missing} non-trading days skipped; "
          f"{days} trading days in {OUT}")
    if partial:
        print(f"{len(partial)} days with an index not published:", *partial[:20], sep="\n  ")
    if errors:
        print(f"{len(errors)} errors:", *errors[:20], sep="\n  ")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
