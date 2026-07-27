#!/usr/bin/env python3
"""
fetch_data.py  —  Pye-Barker Fire & Safety fuel price tracker
Fetches weekly retail gasoline price data from EIA DNAV LeafHandler pages.
Rolls weekly readings up to monthly averages (EIA methodology).
Writes data.json consumed by index.html.

Designed to be robust against EIA page layout changes:
- Multiple parsing strategies tried in order
- Graceful degradation: partial data is better than no data
- Window derived from best available series if US Average fails
"""

import json
import re
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

SERIES = {
    "US Average":              "EMM_EPM0_PTE_NUS_DPG",
    "East Coast (PADD 1)":     "EMM_EPM0_PTE_R10_DPG",
    "Midwest (PADD 2)":        "EMM_EPM0_PTE_R20_DPG",
    "Gulf Coast (PADD 3)":     "EMM_EPM0_PTE_R30_DPG",
    "Rocky Mountain (PADD 4)": "EMM_EPM0_PTE_R40_DPG",
    "West Coast (PADD 5)":     "EMM_EPM0_PTE_R50_DPG",
    "California":              "EMM_EPM0_PTE_SCA_DPG",
    "Colorado":                "EMM_EPM0_PTE_SCO_DPG",
    "Florida":                 "EMM_EPM0_PTE_SFL_DPG",
    "Massachusetts":           "EMM_EPM0_PTE_SMA_DPG",
    "Minnesota":               "EMM_EPM0_PTE_SMN_DPG",
    "New York":                "EMM_EPM0_PTE_SNY_DPG",
    "Ohio":                    "EMM_EPM0_PTE_SOH_DPG",
    "Texas":                   "EMM_EPM0_PTE_STX_DPG",
    "Washington":              "EMM_EPM0_PTE_SWA_DPG",
}

MONTH_MAP = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
    "january":1,"february":2,"march":3,"april":4,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
}


def clean_text(html):
    """Strip HTML, decode entities, collapse whitespace."""
    text = re.sub(r'<[^>]+>', ' ', html)
    # Common HTML entities
    text = text.replace('&nbsp;', ' ').replace('&#160;', ' ')
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = re.sub(r'&#\d+;', ' ', text)
    text = re.sub(r'&\w+;', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n+', '\n', text)
    return text


def parse_price(s):
    """Parse a price string tolerantly — handles '3.456', '3,456', '$3.456'."""
    s = s.strip().lstrip('$').replace(',', '')
    try:
        v = float(s)
        # Sanity check: US fuel prices are between $1 and $10/gal
        if 1.0 <= v <= 10.0:
            return v
    except ValueError:
        pass
    return None


def parse_month(s):
    """Parse month name or number to int 1-12."""
    s = s.strip().lower()
    if s in MONTH_MAP:
        return MONTH_MAP[s]
    try:
        v = int(s)
        if 1 <= v <= 12:
            return v
    except ValueError:
        pass
    return None


def parse_day(s):
    """Parse day string to int 1-31."""
    try:
        v = int(s.strip())
        if 1 <= v <= 31:
            return v
    except ValueError:
        pass
    return None


def build_date(year, mon, mo, dy):
    """Build YYYY-MM-DD, handling Dec→Jan year boundary."""
    yr = year + 1 if (mo == 1 and mon == 12) else year
    return f"{yr}-{mo:02d}-{dy:02d}"


def strategy_anchor_chunks(text):
    """
    Primary strategy: find YYYY-Mon anchors, extract MM/DD + price pairs
    from the following chunk. Handles both zero-padded (05/12) and
    non-zero-padded (5/12) date formats.
    """
    readings = {}

    # Match: 2026-Jul, 2026 Jul, 2026/Jul, 2026-July, etc.
    anchor_re = re.compile(
        r'\b(\d{4})\s*[-/]\s*(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|'
        r'May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|'
        r'Nov(?:ember)?|Dec(?:ember)?)\b',
        re.IGNORECASE
    )
    # Match date/value pairs: MM/DD followed by a price
    # Flexible: 1-2 digit month/day, any whitespace separator
    pair_re = re.compile(
        r'\b(\d{1,2})/(\d{1,2})\b[\s,;|:]+(\$?[\d,]+\.\d+)'
    )

    anchors = list(anchor_re.finditer(text))
    for idx, anchor in enumerate(anchors):
        year = int(anchor.group(1))
        mon  = parse_month(anchor.group(2))
        if not mon:
            continue
        start = anchor.end()
        # Chunk ends at next anchor start, capped at 600 chars
        end = min(anchors[idx + 1].start() if idx + 1 < len(anchors) else start + 600,
                  start + 600)
        chunk = text[start:end]

        for pair in pair_re.finditer(chunk):
            mo  = parse_day(pair.group(1))
            dy  = parse_day(pair.group(2))
            val = parse_price(pair.group(3))
            if mo and dy and val and 1 <= mo <= 12:
                readings[build_date(year, mon, mo, dy)] = val

    return readings


def strategy_table_cells(text):
    """
    Fallback strategy: scan for any sequence of year-month + date + price
    without requiring them to be adjacent. More permissive.
    """
    readings = {}

    # Find all standalone prices (plausible fuel price values)
    # Preceded somewhere nearby by a date pattern
    block_re = re.compile(
        r'\b(\d{4})\s*[-/]\s*(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|'
        r'May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|'
        r'Nov(?:ember)?|Dec(?:ember)?)'
        r'([\s\S]{0,800}?)'   # up to 800 chars of anything
        r'\b(\d{1,2})/(\d{1,2})\b'
        r'[\s\S]{0,50}?'
        r'(\$?[1-9]\d*\.\d{3})',  # price must have exactly 3 decimal places
        re.IGNORECASE
    )
    for m in block_re.finditer(text):
        year = int(m.group(1))
        mon  = parse_month(m.group(2))
        mo   = parse_day(m.group(4))
        dy   = parse_day(m.group(5))
        val  = parse_price(m.group(6))
        if mon and mo and dy and val and 1 <= mo <= 12:
            readings[build_date(year, mon, mo, dy)] = val

    return readings


def strategy_consecutive_prices(text):
    """
    Last resort: find rows of the form YYYY-Mon followed by up to 5
    consecutive price values (no date required). Assign dates sequentially
    starting from the 1st Monday of that month — less accurate but better
    than nothing.
    """
    readings = {}

    row_re = re.compile(
        r'\b(\d{4})\s*[-/]\s*(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|'
        r'May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|'
        r'Nov(?:ember)?|Dec(?:ember)?)\b'
        r'((?:\s+\$?[1-9]\d*\.\d{3}){1,5})',
        re.IGNORECASE
    )
    price_re = re.compile(r'\$?([1-9]\d*\.\d{3})')

    for row in row_re.finditer(text):
        year = int(row.group(1))
        mon  = parse_month(row.group(2))
        if not mon:
            continue
        prices = [float(p) for p in price_re.findall(row.group(3))
                  if 1.0 <= float(p) <= 10.0]
        for i, val in enumerate(prices):
            # Approximate: weekly EIA data is always Monday, 7 days apart
            # Use day offsets 7, 14, 21, 28, 35 within month
            day = (i + 1) * 7
            if day > 31:
                continue
            date_str = f"{year}-{mon:02d}-{min(day, 28):02d}"
            readings[date_str] = val

    return readings


def fetch_weekly(series_id):
    """
    Fetch EIA LeafHandler page and extract weekly readings using
    multiple strategies in order of reliability.
    Returns list of {"date": "YYYY-MM-DD", "value": float} oldest-first.
    """
    url = f"https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s={series_id}&f=W"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "Chrome/120.0.0.0 Safari/537.36"
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    text = clean_text(html)

    # Try strategies in order, use first that returns data
    for strategy in [strategy_anchor_chunks, strategy_table_cells,
                     strategy_consecutive_prices]:
        readings = strategy(text)
        if readings:
            result = [{"date": d, "value": v}
                      for d, v in sorted(readings.items())]
            return result

    return []


def rollup_monthly(weekly_readings, window_months=13):
    """Average weekly readings by YYYY-MM, return last window_months months."""
    by_month = defaultdict(list)
    for r in weekly_readings:
        by_month[r["date"][:7]].append(r["value"])

    monthly = sorted(
        [{"period": ym, "value": round(sum(v) / len(v), 3)}
         for ym, v in by_month.items() if v],
        key=lambda x: x["period"]
    )
    return monthly[-window_months:]


def main():
    print(f"Fetching weekly EIA data for {len(SERIES)} series...")
    errors      = []
    monthly_out = {}
    last4_out   = {}
    prev4_out   = {}

    for label, sid in SERIES.items():
        try:
            wk = fetch_weekly(sid)
            if not wk:
                raise ValueError("No data parsed — all strategies failed")

            monthly_out[label] = rollup_monthly(wk, window_months=13)
            last4_out[label]   = wk[-4:] if len(wk) >= 4 else wk
            prev_pool          = wk[:-4] if len(wk) > 4 else []
            prev4_out[label]   = prev_pool[-4:] if len(prev_pool) >= 4 else prev_pool

            latest_wk = wk[-1]["date"] if wk else "—"
            latest_mo = monthly_out[label][-1]["period"] if monthly_out[label] else "—"
            print(f"  OK {label}: {len(wk)} weeks · latest {latest_wk} · month {latest_mo}")

        except Exception as e:
            print(f"  FAIL {label}: {e}")
            errors.append(label)

    # Build window from US Average if available, else longest available series
    if "US Average" in monthly_out and monthly_out["US Average"]:
        us_monthly = monthly_out["US Average"]
    elif monthly_out:
        us_monthly = max(monthly_out.values(), key=len)
    else:
        us_monthly = []

    window = [r["period"] for r in us_monthly]

    # L4W label from US Average weekly dates if available
    us_last4 = last4_out.get("US Average", [])
    if len(us_last4) == 4:
        def fmt(d):
            p  = d.split("-")
            mn = ["","Jan","Feb","Mar","Apr","May","Jun",
                  "Jul","Aug","Sep","Oct","Nov","Dec"]
            return f"{mn[int(p[1])]} {int(p[2])}"
        l4w_label = (f"{fmt(us_last4[0]['date'])} \u2013 "
                     f"{fmt(us_last4[-1]['date'])} '{us_last4[-1]['date'][2:4]}")
    else:
        l4w_label = "Last 4 weeks"

    payload = {
        "fetched_at":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window":       window,
        "l4w_label":    l4w_label,
        "series":       monthly_out,
        "weekly_last4": last4_out,
        "weekly_prev4": prev4_out,
        "errors":       errors,
    }

    with open("data.json", "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    status = "clean" if not errors else f"WARNING: {len(errors)} failed: {errors}"
    print(f"\nWrote data.json · window "
          f"{window[0] if window else '?'} to {window[-1] if window else '?'} · {status}")


if __name__ == "__main__":
    main()
