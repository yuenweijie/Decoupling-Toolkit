# URA Auto-Update — Setup Guide

Keeps the Decoupling Calculator's price benchmarks current from the official **URA Data Service API**:
resale prices by unit type, new-launch prices by region (OCR/RCR/CCR), and PSF guides.

All files live in this folder:

| File | What it is |
|---|---|
| `ura_update.py` | The script that pulls URA data and updates the calculator. |
| `ura_projects.json` | **Your editable whitelist** of qualifying resale projects. |
| `run_ura_update.command` | Double-click to run the update on demand (Mac). |
| `com.wesley.uraupdate.plist` | The schedule (Tue/Fri auto-run). |
| `ura_key.txt` | **You create this** — holds your URA Access Key. Never share it. |

---

## Step 1 — Put your Access Key in a file (one time)

1. In this folder, create a new plain-text file named exactly **`ura_key.txt`**.
2. Paste your URA Access Key into it — just the key, one line, nothing else. Save.

The script reads the key only from this file. It is never written into the calculator or any shared file. Keep `ura_key.txt` private (don't email it or upload it anywhere).

## Step 2 — Check Python is available (one time)

Macs include Python 3. Open **Terminal** and run:

```
python3 --version
```

If you see a version number (e.g. `Python 3.x`), you're set. If not, install from python.org.

## Step 3 — Run it once to test

In Terminal:

```
cd "/Users/yuenweijie/Desktop/Co-work Battlefield/Decoupling Calculator/Decoupling Advisory"
python3 ura_update.py
```

You should see it request a token, pull 4 batches, print the computed figures, and report
`Updated N/10 fields`. Re-open `Decoupling_Calculator.html` and the Assumptions figures will reflect the latest URA numbers.

> First-run note: the parsing follows URA's documented field names. If the printed figures look empty or odd, copy the console output to me and I'll tune the field mapping — this is normal for a first connection.

## Step 4 (optional) — Double-click runner

Instead of Terminal, you can run `run_ura_update.command` by double-clicking it.
One-time enablement in Terminal:

```
chmod +x "run_ura_update.command"
```

(If macOS blocks it the first time: right-click → Open → Open.)

## Step 5 — Schedule it twice a week (Tue & Fri)

URA refreshes transactions every Tuesday and Friday end-of-day, so the schedule runs at 19:30 on those days.

```
cp "com.wesley.uraupdate.plist" ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.wesley.uraupdate.plist
```

To stop it later:

```
launchctl unload ~/Library/LaunchAgents/com.wesley.uraupdate.plist
```

Output from each run is logged to `ura_update.log` in this folder.

---

## Editing your project whitelist

Open `ura_projects.json` and edit the `resale_projects` list. This is where your criteria live —
**>200 units, within ~800m of MRT/LRT, 70+ years remaining lease, near amenities, rentable** — because the
URA API does **not** carry unit count, lease, or MRT distance. You vet the projects once; the API keeps their
prices current.

- Names must match URA's exact project spelling (uppercase). Find them on the
  [URA transaction search](https://eservice.ura.gov.sg/property-market-information/pmiResidentialTransactionSearch).
- Add or remove freely; the more qualifying projects, the more stable the averages.
- New-launch-by-region and PSF figures are computed across **all** new-sale / private transactions by market
  segment, so they don't need a whitelist.

## What gets updated, and the honest limits

- **Resale by unit type (2BR–5BR):** median resale price of your whitelisted projects, last 12 months.
  Bedroom is inferred from floor area (bands are editable near the top of `ura_update.py`).
- **New launch by region:** median new-sale price of 2–3BR units per OCR/RCR/CCR.
- **PSF by region:** median $/sqft per OCR/RCR/CCR.

Limits to keep in mind: bedroom count is an area-based approximation (URA gives floor area, not bedrooms);
the ">200 units / lease / MRT" criteria are enforced by *your whitelist*, not the API; and these are medians
across a basket, not the exact unit a client is eyeing — always sanity-check a specific project's caveats before advising.
