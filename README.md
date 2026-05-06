# US Retail Fuel Prices — EIA Tracker

Interactive chart of US retail gasoline prices by region, state, and city. Data sourced directly from the [U.S. Energy Information Administration (EIA)](https://www.eia.gov/petroleum/gasdiesel/) and refreshed daily.

## Live site
Once deployed to GitHub Pages, your site will be at:
`https://<your-username>.github.io/<repo-name>/`

## How it works

- **`data.json`** — the data file read by the webpage. Contains the last 13 months of monthly average retail gasoline prices for 20 EIA series (PADD regions, states, and cities).
- **`fetch_data.py`** — Python script that fetches fresh data from EIA's public DNAV pages and rewrites `data.json`. No API key required.
- **`.github/workflows/refresh.yml`** — GitHub Actions workflow that runs `fetch_data.py` every day at ~9am ET and commits the updated `data.json` if data changed.
- **`index.html`** — the self-contained webpage. Reads `data.json` on load; no server required.

## Setup (one time)

### 1. Create the GitHub repository

```bash
git init
git add .
git commit -m "initial commit"
gh repo create eia-fuel-tracker --public --push
```

Or create the repo at github.com and push manually.

### 2. Enable GitHub Pages

1. Go to your repo → **Settings** → **Pages**
2. Under **Source**, select **Deploy from a branch**
3. Select `main` branch, `/ (root)` folder
4. Click **Save**

Your site will be live at `https://<username>.github.io/<repo>/` within a minute.

### 3. Verify the Actions workflow runs

Go to the **Actions** tab in your repo. The `Refresh EIA Data` workflow runs daily. You can also trigger it manually via **Run workflow**.

## Updating manually

```bash
python3 fetch_data.py
git add data.json
git commit -m "refresh data"
git push
```

## Series included

| Label | EIA Series ID |
|---|---|
| US Average | EMM_EPM0_PTE_NUS_DPG |
| East Coast (PADD 1) | EMM_EPM0_PTE_R10_DPG |
| Midwest (PADD 2) | EMM_EPM0_PTE_R20_DPG |
| Gulf Coast (PADD 3) | EMM_EPM0_PTE_R30_DPG |
| Rocky Mtn (PADD 4) | EMM_EPM0_PTE_R40_DPG |
| West Coast (PADD 5) | EMM_EPM0_PTE_R50_DPG |
| California | EMM_EPM0_PTE_SCA_DPG |
| Colorado | EMM_EPM0_PTE_SCO_DPG |
| Florida | EMM_EPM0_PTE_SFL_DPG |
| Massachusetts | EMM_EPM0_PTE_SMA_DPG |
| Minnesota | EMM_EPM0_PTE_SMN_DPG |
| New York | EMM_EPM0_PTE_SNY_DPG |
| Ohio | EMM_EPM0_PTE_SOH_DPG |
| Texas | EMM_EPM0_PTE_STX_DPG |
| Washington | EMM_EPM0_PTE_SWA_DPG |
| Boston | EMM_EPM0_PTE_YBOS_DPG |
| Chicago | EMM_EPM0_PTE_YORD_DPG |
| Denver | EMM_EPM0_PTE_YDEN_DPG |
| Houston | EMM_EPM0_PTE_Y44HO_DPG |
| Los Angeles | EMM_EPM0_PTE_Y05LA_DPG |

## Adding your internal data (future)

When ready to overlay your own fuel surcharge or cost data, add a `internal_data.json` file in the same format as `data.json` and load it alongside the EIA data in `index.html`. The chart can then show a third line per selected region for direct comparison.
