#!/usr/bin/env python3
"""
fetch_data.py
Fetches monthly retail gasoline price data from EIA DNAV LeafHandler pages.
Writes data.json consumed by index.html.
Run daily by GitHub Actions — no API key required.
"""

import json
import re
import urllib.request
from datetime import datetime, timezone

SERIES = {
    "US Average":          "EMM_EPM0_PTE_NUS_DPG",
    "East Coast (PADD 1)": "EMM_EPM0_PTE_R10_DPG",
    "Midwest (PADD 2)":    "EMM_EPM0_PTE_R20_DPG",
    "Gulf Coast (PADD 3)": "EMM_EPM0_PTE_R30_DPG",
    "Rocky Mtn (PADD 4)":  "EMM_EPM0_PTE_R40_DPG",
    "West Coast (PADD 5)": "EMM_EPM0_PTE_R50_DPG",
    "California":          "EMM_EPM0_PTE_SCA_DPG",
    "Colorado":            "EMM_EPM0_PTE_SCO_DPG",
    "Florida":             "EMM_EPM0_PTE_SFL_DPG",
    "Massachusetts":       "EMM_EPM0_PTE_SMA_DPG",
    "Minnesota":           "EMM_EPM0_PTE_SMN_DPG",
    "New York":            "EMM_EPM0_PTE_SNY_DPG",
    "Ohio":                "EMM_EPM0_PTE_SOH_DPG",
    "Texas":               "EMM_EPM0_PTE_STX_DPG",
    "Washington":          "EMM_EPM0_PTE_SWA_DPG",
    "Boston":              "EMM_EPM0_PTE_YBOS_DPG",
    "Chicago":             "EMM_EPM0_PTE_YORD_DPG",
    "Denver":              "EMM_EPM0_PTE_YDEN_DPG",
    "Houston":             "EMM_EPM0_PTE_Y44HO_DPG",
    "Los Angeles":         "EMM_EPM0_PTE_Y05LA_DPG",
}

MONTHS_ORDER = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def fetch_series(series_id):
    """Fetch a single LeafHandler page and return dict of {YYYY-MM: value}."""
    url = f"https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s={series_id}&f=M"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    # Parse the year/month table. Rows look like:
    # <td>2025</td><td>3.196</td><td>3.247</td>...
    # We extract year rows then map col index to month
    results = {}
    # Find all table rows containing a 4-digit year
    row_pattern = re.compile(
        r'<tr[^>]*>\s*(?:<td[^>]*>\s*(?:&nbsp;|\s)*</td>\s*)?'
        r'<td[^>]*>\s*(\d{4})\s*</td>'
        r'((?:\s*<td[^>]*>[^<]*</td>){1,12})',
        re.IGNORECASE | re.DOTALL
    )
    cell_pattern = re.compile(r'<td[^>]*>\s*([0-9.]+|-|--| |&nbsp;)\s*</td>', re.IGNORECASE)

    for m in row_pattern.finditer(html):
        year = int(m.group(1))
        cells_html = m.group(2)
        vals = cell_pattern.findall(cells_html)
        for col_idx, raw in enumerate(vals):
            raw = raw.strip()
            if raw in ("", "-", "--", "&nbsp;", " "):
                continue
            try:
                v = float(raw)
            except ValueError:
                continue
            month_name = MONTHS_ORDER[col_idx]
            key = f"{year}-{MONTHS_ORDER.index(month_name)+1:02d}"
            results[key] = v

    return results


def build_rolling_12(all_data_by_series):
    """
    Given {label: {YYYY-MM: value}}, find the latest common period
    and return the last 13 months for each series as a sorted list of
    {period, value} objects.
    """
    # Collect all available periods across all series
    all_periods = set()
    for d in all_data_by_series.values():
        all_periods.update(d.keys())

    sorted_periods = sorted(all_periods)
    # Take the latest 13 months present in the US Average series (most reliable)
    us_periods = sorted(all_data_by_series.get("US Average", {}).keys())
    window = us_periods[-13:] if len(us_periods) >= 13 else us_periods

    output = {}
    for label, data in all_data_by_series.items():
        output[label] = [
            {"period": p, "value": data[p]}
            for p in window
            if p in data
        ]

    return output, window


def main():
    print(f"Fetching {len(SERIES)} EIA series...")
    raw = {}
    errors = []

    for label, sid in SERIES.items():
        try:
            data = fetch_series(sid)
            raw[label] = data
            latest = max(data.keys()) if data else "none"
            print(f"  {label}: {len(data)} months, latest={latest}")
        except Exception as e:
            print(f"  ERROR {label}: {e}")
            errors.append(label)

    series_data, window = build_rolling_12(raw)

    payload = {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": window,
        "series": series_data,
        "errors": errors,
    }

    with open("data.json", "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    print(f"\nWrote data.json — window: {window[0] if window else '?'} to {window[-1] if window else '?'}")
    if errors:
        print(f"WARNING: Failed series: {errors}")


if __name__ == "__main__":
    main()
