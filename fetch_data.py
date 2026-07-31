#!/usr/bin/env python3
"""
fetch_data.py  —  Pye-Barker Fire & Safety fuel price tracker
Fetches weekly retail gasoline price data from EIA DNAV LeafHandler pages.
Rolls weekly readings up to monthly averages (EIA methodology).
Writes data.json consumed by index.html.

Parser handles the EIA table format:
| 2026-Jun | 06/01 | 4.439 | 06/08 | 4.281 | 06/15 | 4.187 | | | | |
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
}


def fetch_weekly(series_id):
    """
    Fetch EIA LeafHandler page and parse all weekly readings.
    Returns list of {"date": "YYYY-MM-DD", "value": float} oldest-first.
    """
    url = f"https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s={series_id}&f=W"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    # Strip HTML tags
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'&nbsp;|&#160;', ' ', text)
    text = re.sub(r'\s+', ' ', text)

    readings = {}

    # Primary: parse table rows
    # Pattern: YYYY-Mon followed by pairs of MM/DD and price values
    # Handles both plain text and pipe-separated table formats
    row_re = re.compile(
        r'\b(\d{4})[- ](Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b'
        r'([\s\S]{0,500}?)(?=\d{4}[- ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b|$)',
        re.IGNORECASE
    )
    # Match MM/DD followed by a fuel price (1.xxx to 9.xxx)
    pair_re = re.compile(r'\b(\d{1,2})/(\d{1,2})\b\s*[\|,\s]+\s*([1-9]\.\d{3})\b')

    for row in row_re.finditer(text):
        year = int(row.group(1))
        mon  = MONTH_MAP[row.group(2).lower()]
        chunk = row.group(3)

        for pair in pair_re.finditer(chunk):
            mo  = int(pair.group(1))
            dy  = int(pair.group(2))
            val = float(pair.group(3))
            if not (1 <= mo <= 12 and 1 <= dy <= 31):
                continue
            # Handle Dec row with Jan dates (year boundary)
            yr = year + 1 if (mo == 1 and mon == 12) else year
            date_str = f"{yr}-{mo:02d}-{dy:02d}"
            readings[date_str] = val

    # Fallback: broader scan if primary found nothing
    if not readings:
        broad_re = re.compile(
            r'\b(\d{4})[- ](Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b'
            r'.*?(\d{1,2})/(\d{1,2}).*?([1-9]\.\d{3})',
            re.IGNORECASE | re.DOTALL
        )
        for m in broad_re.finditer(text):
            year = int(m.group(1))
            mon  = MONTH_MAP[m.group(2).lower()]
            mo, dy, val = int(m.group(3)), int(m.group(4)), float(m.group(5))
            if not (1 <= mo <= 12 and 1 <= dy <= 31):
                continue
            yr = year + 1 if (mo == 1 and mon == 12) else year
            readings[f"{yr}-{mo:02d}-{dy:02d}"] = val

    return [{"date": d, "value": v} for d, v in sorted(readings.items())]


def rollup_monthly(weekly_readings, window_months=13):
    """Average weekly readings by YYYY-MM, return last window_months months."""
    by_month = defaultdict(list)
    for r in weekly_readings:
        by_month[r["date"][:7]].append(r["value"])
    monthly = sorted(
        [{"period": ym, "value": round(sum(v)/len(v), 3)}
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
                raise ValueError("No data parsed")

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

    # Build window — use US Average if available, else longest series
    if "US Average" in monthly_out and monthly_out["US Average"]:
        us_monthly = monthly_out["US Average"]
    elif monthly_out:
        us_monthly = max(monthly_out.values(), key=len)
    else:
        us_monthly = []

    window = [r["period"] for r in us_monthly]

    # L4W label
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
    print(f"\nWrote data.json · {window[0] if window else '?'} to "
          f"{window[-1] if window else '?'} · {status}")


if __name__ == "__main__":
    main()
