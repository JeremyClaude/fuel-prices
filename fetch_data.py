#!/usr/bin/env python3
"""
fetch_data.py  —  Pye-Barker Fire & Safety fuel price tracker
Fetches weekly retail gasoline prices from the official EIA Open Data API v2.
Rolls weekly readings up to monthly averages, writes data.json for index.html.

Resilience:
- Single batched API call for all 15 series (one request, not 15)
- Retry with backoff on API failure
- Merge-with-previous: a failed series keeps its last known data,
  so the site never breaks
API key is read from the EIA_API_KEY environment variable
(stored as a GitHub Actions secret — never in this file or the repo).
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone

API_KEY = os.environ.get("EIA_API_KEY", "").strip()

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
ID_TO_LABEL = {v: k for k, v in SERIES.items()}

API_URL = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"


def fetch_all_weekly(retries=3, backoff=20):
    """
    One batched API request for all series, weekly frequency.
    Returns {label: [{"date": "YYYY-MM-DD", "value": float}, ...]} oldest-first.
    Raises on total failure after retries.
    """
    params = [
        ("api_key", API_KEY),
        ("frequency", "weekly"),
        ("data[0]", "value"),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "desc"),
        ("length", "2000"),   # 15 series x ~60 weeks = ~900 rows; ample headroom
    ]
    for sid in SERIES.values():
        params.append(("facets[series][]", sid))

    url = API_URL + "?" + urllib.parse.urlencode(params)

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PyeBarker-FuelTracker/1.0"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                payload = json.loads(resp.read().decode("utf-8"))

            rows = payload.get("response", {}).get("data", [])
            if not rows:
                raise ValueError(f"API returned no rows: {json.dumps(payload)[:300]}")

            by_label = defaultdict(dict)
            for row in rows:
                sid    = row.get("series")
                period = row.get("period")       # "YYYY-MM-DD"
                raw    = row.get("value")
                label  = ID_TO_LABEL.get(sid)
                if not (label and period and raw is not None):
                    continue
                try:
                    val = float(raw)
                except (TypeError, ValueError):
                    continue
                if 0.5 <= val <= 15.0:           # sanity bounds
                    by_label[label][period] = val

            return {
                label: [{"date": d, "value": v} for d, v in sorted(dates.items())]
                for label, dates in by_label.items()
            }

        except Exception as e:
            last_err = e
            print(f"  API attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)

    raise RuntimeError(f"All API attempts failed: {last_err}")


def rollup_monthly(weekly, window_months=13):
    by_month = defaultdict(list)
    for r in weekly:
        by_month[r["date"][:7]].append(r["value"])
    monthly = sorted(
        [{"period": ym, "value": round(sum(v) / len(v), 3)}
         for ym, v in by_month.items() if v],
        key=lambda x: x["period"]
    )
    return monthly[-window_months:]


def load_previous():
    """Load existing data.json so failed series can keep last known data."""
    try:
        with open("data.json") as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    if not API_KEY:
        print("FATAL: EIA_API_KEY environment variable is not set.")
        sys.exit(1)

    prev = load_previous()
    print(f"Fetching {len(SERIES)} series from EIA API v2 (single batched call)...")

    errors, stale = [], []
    monthly_out, last4_out, prev4_out = {}, {}, {}

    try:
        all_weekly = fetch_all_weekly()
    except Exception as e:
        print(f"API completely unavailable: {e}")
        all_weekly = {}

    for label in SERIES:
        wk = all_weekly.get(label, [])
        if wk:
            monthly_out[label] = rollup_monthly(wk)
            last4_out[label]   = wk[-4:]
            prev_pool          = wk[:-4]
            prev4_out[label]   = prev_pool[-4:] if len(prev_pool) >= 4 else prev_pool
            print(f"  OK {label}: {len(wk)} weeks · latest {wk[-1]['date']}")
        else:
            # Merge: keep previous data if we had any
            p_series = (prev.get("series") or {}).get(label)
            p_last4  = (prev.get("weekly_last4") or {}).get(label)
            p_prev4  = (prev.get("weekly_prev4") or {}).get(label)
            if p_series:
                monthly_out[label] = p_series
                last4_out[label]   = p_last4 or []
                prev4_out[label]   = p_prev4 or []
                stale.append(label)
                print(f"  STALE {label}: API returned nothing — kept previous data")
            else:
                errors.append(label)
                print(f"  FAIL {label}: no fresh or previous data")

    us_monthly = monthly_out.get("US Average") or (
        max(monthly_out.values(), key=len) if monthly_out else []
    )
    window = [r["period"] for r in us_monthly]

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
        "stale":        stale,
        "errors":       errors,
    }

    with open("data.json", "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    status = "clean" if not (errors or stale) else f"stale={stale} errors={errors}"
    print(f"\nWrote data.json · {window[0] if window else '?'} to "
          f"{window[-1] if window else '?'} · {status}")

    # Exit non-zero ONLY if we truly have nothing (so GitHub alerts you)
    if errors and not monthly_out:
        sys.exit(1)


if __name__ == "__main__":
    main()
