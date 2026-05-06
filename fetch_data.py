#!/usr/bin/env python3
"""
fetch_data.py
Fetches weekly retail gasoline price data from EIA DNAV LeafHandler pages.
Rolls weekly readings up to monthly averages (EIA methodology).
Stores last 4 and prior 4 weekly readings per series.
Writes data.json consumed by index.html.
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
    "Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
    "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12
}


def fetch_weekly(series_id):
    """
    Fetch EIA LeafHandler page and extract weekly readings.
    The page contains a table with rows like:
      <td>2025-May</td><td>05/05</td><td>3.296</td><td>05/12</td><td>3.305</td>...
    Returns list of {"date": "YYYY-MM-DD", "value": float} sorted oldest-first.
    """
    url = f"https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s={series_id}&f=W"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    # Strip all HTML tags to get plain text, then parse
    # Each row looks like: 2025-May  05/05  3.296  05/12  3.305  05/19  3.289  05/26  3.261
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'\s+', ' ', text)

    readings = {}

    # Find year-month markers followed by date/value pairs
    # Pattern: YYYY-Mon followed by pairs of MM/DD and decimal values
    row_pattern = re.compile(
        r'(\d{4})-(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+'
        r'((?:\d{2}/\d{2}\s+[\d.]+\s*){1,5})',
        re.IGNORECASE
    )
    pair_pattern = re.compile(r'(\d{2}/\d{2})\s+([\d.]+)')

    for row in row_pattern.finditer(text):
        year = int(row.group(1))
        mon  = MONTH_MAP[row.group(2).capitalize()]
        seg  = row.group(3)

        for pair in pair_pattern.finditer(seg):
            md  = pair.group(1)   # MM/DD
            val = float(pair.group(2))
            mo_str, dy_str = md.split("/")
            mo, dy = int(mo_str), int(dy_str)

            # Handle year boundary: Dec row with Jan dates
            yr = year
            if mo == 1 and mon == 12:
                yr = year + 1

            date_str = f"{yr}-{mo:02d}-{dy:02d}"
            readings[date_str] = val

    result = [{"date": d, "value": v} for d, v in sorted(readings.items())]
    return result


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
    errors = []
    monthly_out = {}
    last4_out   = {}
    prev4_out   = {}

    for label, sid in SERIES.items():
        try:
            wk = fetch_weekly(sid)
            if not wk:
                raise ValueError("No data parsed from page")

            monthly_out[label] = rollup_monthly(wk, window_months=13)
            last4_out[label]   = wk[-4:] if len(wk) >= 4 else wk
            prev_pool          = wk[:-4] if len(wk) > 4 else []
            prev4_out[label]   = prev_pool[-4:] if len(prev_pool) >= 4 else prev_pool

            latest_wk = wk[-1]["date"] if wk else "—"
            latest_mo = monthly_out[label][-1]["period"] if monthly_out[label] else "—"
            print(f"  {label}: {len(wk)} weeks · latest {latest_wk} · month {latest_mo}")

        except Exception as e:
            print(f"  ERROR {label}: {e}")
            errors.append(label)

    us_monthly = monthly_out.get("US Average", [])
    window = [r["period"] for r in us_monthly]

    us_last4_dates = [r["date"] for r in last4_out.get("US Average", [])]
    if len(us_last4_dates) == 4:
        def fmt(d):
            parts = d.split("-")
            months = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
            return f"{months[int(parts[1])]} {int(parts[2])}"
        l4w_label = f"{fmt(us_last4_dates[0])} \u2013 {fmt(us_last4_dates[-1])} '{us_last4_dates[-1][2:4]}"
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

    print(f"\nWrote data.json · window {window[0] if window else '?'} → {window[-1] if window else '?'} · L4W: {l4w_label}")
    if errors:
        print(f"WARNING: Failed series: {errors}")


if __name__ == "__main__":
    main()
