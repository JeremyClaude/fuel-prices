#!/usr/bin/env python3
"""
fetch_data.py
Fetches weekly retail gasoline price data from EIA DNAV LeafHandler pages.
Rolls weekly readings up to monthly averages (EIA methodology: simple average of weeks in month).
Stores last 4 and prior 4 weekly readings per series for the rolling 4-week feature.
Writes data.json consumed by index.html.
Run daily by GitHub Actions — no API key required.
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
    Fetch weekly LeafHandler page and return list of
    {"date": "YYYY-MM-DD", "value": float} sorted oldest-first.
    Page layout: Year-Month rows with week columns showing MM/DD | value.
    """
    url = f"https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s={series_id}&f=W"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    readings = []

    # Parse rows like: | 2025-May | 05/05 | 3.296 | 05/12 | 3.305 | ...
    row_re = re.compile(
        r'\|\s*(\d{4})-(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*\|'
        r'((?:\s*(?:\d{2}/\d{2})?\s*\|\s*(?:[0-9.]+|-)?\s*\|?){1,10})',
        re.IGNORECASE
    )
    cell_re = re.compile(r'(\d{2}/(\d{2}))\s*\|\s*([0-9]+\.[0-9]+)')

    for m in row_re.finditer(html):
        year = int(m.group(1))
        mon  = MONTH_MAP[m.group(2).capitalize()]
        seg  = m.group(3)
        for cell in cell_re.finditer(seg):
            md_str = cell.group(1)   # e.g. "05/05"
            val    = float(cell.group(3))
            mo_str, dy_str = md_str.split("/")
            mo, dy = int(mo_str), int(dy_str)
            # Determine full year for the week-ending date
            yr = year
            if mo < mon - 1:   # crossed into next year (Dec row, Jan date)
                yr = year + 1
            date_str = f"{yr}-{mo:02d}-{dy:02d}"
            readings.append({"date": date_str, "value": val})

    # Deduplicate (same date may appear in adjacent rows near month boundary)
    seen = {}
    for r in readings:
        seen[r["date"]] = r["value"]

    return [{"date": d, "value": v} for d, v in sorted(seen.items())]


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
    monthly_out  = {}
    last4_out    = {}
    prev4_out    = {}

    for label, sid in SERIES.items():
        try:
            wk = fetch_weekly(sid)
            if not wk:
                raise ValueError("No data returned")

            monthly_out[label] = rollup_monthly(wk, window_months=13)

            # Last 4 weekly readings
            last4 = wk[-4:] if len(wk) >= 4 else wk
            last4_out[label] = last4

            # Prior 4 weekly readings (weeks 5-8 ago)
            prev_pool = wk[:-4] if len(wk) > 4 else []
            prev4_out[label] = prev_pool[-4:] if len(prev_pool) >= 4 else prev_pool

            latest_wk = wk[-1]["date"] if wk else "—"
            latest_mo = monthly_out[label][-1]["period"] if monthly_out[label] else "—"
            print(f"  {label}: {len(wk)} weeks · latest week {latest_wk} · latest month {latest_mo}")

        except Exception as e:
            print(f"  ERROR {label}: {e}")
            errors.append(label)

    us_monthly = monthly_out.get("US Average", [])
    window = [r["period"] for r in us_monthly]

    # Build L4W label from actual week-ending dates
    us_last4_dates = [r["date"] for r in last4_out.get("US Average", [])]
    if len(us_last4_dates) == 4:
        def fmt(d):
            parts = d.split("-")
            months = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
            return f"{months[int(parts[1])]} {int(parts[2])}"
        l4w_label = f"{fmt(us_last4_dates[0])} – {fmt(us_last4_dates[-1])} '{us_last4_dates[-1][2:4]}"
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
