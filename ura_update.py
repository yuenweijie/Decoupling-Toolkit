#!/usr/bin/env python3
"""
URA benchmark updater for the Decoupling Toolkit.

What it does
------------
1. Reads the URA Access Key from the URA_ACCESS_KEY env var (GitHub Actions) or
   `ura_key.txt` (local, gitignored).
2. Requests a daily Token from the URA Data Service.
3. Pulls the latest private residential transactions (PMI_Resi_Transaction, 4 batches).
4. Rebuilds the two price matrices embedded in Decoupling_Calculator.html:
   MATRIX (resale, 70+ yrs lease / freehold) and NEWLAUNCH — median transacted
   price over the last 12 months, by region (OCR/RCR/CCR) x bedroom band (by size).

Normally run by the GitHub Action "Update URA benchmarks" (daily 7:30pm SGT),
which then copies Decoupling_Calculator.html to index.html and commits.

NOTE: parsing follows URA's documented field names. If a run looks empty/odd,
paste the console output back and it can be tuned in minutes.
"""

import json, re, sys, os, ssl, time, urllib.request, urllib.error
from datetime import date, datetime
from statistics import median

HERE          = os.path.dirname(os.path.abspath(__file__))
KEY_FILE      = os.path.join(HERE, "ura_key.txt")
CALC_HTML     = os.path.join(HERE, "Decoupling_Calculator.html")

MONTHS_BACK   = 12         # look-back window for transactions
ENTRY_PCTILE  = 0.20       # percentile used for the informational PSF log line
MIN_LEASE_YEARS = 70       # only include units with at least this many years of lease remaining (freehold always qualifies)
TOKEN_URL     = "https://eservice.ura.gov.sg/uraDataService/insertNewToken/v1"
DATA_URL      = "https://eservice.ura.gov.sg/uraDataService/invokeUraDS/v1?service=PMI_Resi_Transaction&batch={batch}"
UA            = "Mozilla/5.0 (decoupling-calculator-updater)"
SQM_TO_SQFT   = 10.7639
PRIVATE_TYPES = {"Condominium", "Apartment", "Executive Condominium"}


def read_key():
    # Cloud (GitHub Actions) provides the key via an environment variable; locally it's in ura_key.txt.
    env = os.environ.get("URA_ACCESS_KEY", "").strip()
    if env:
        return env
    if not os.path.exists(KEY_FILE):
        sys.exit("No key found — set URA_ACCESS_KEY env var, or create ura_key.txt with your URA Access Key.")
    key = open(KEY_FILE, encoding="utf-8").read().strip()
    if not key:
        sys.exit("ura_key.txt is empty.")
    return key


def http_get(url, headers, retries=3, timeout=120):
    ctx = ssl.create_default_context()
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                raw = r.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="replace")     # URA names can carry accented bytes
            return json.loads(text)
        except urllib.error.HTTPError:
            raise  # real HTTP response (401/500 etc.) — retrying won't help; let callers handle
        except (TimeoutError, urllib.error.URLError, ssl.SSLError, OSError) as e:
            if attempt >= retries:
                raise
            wait = attempt * 10  # 10s, then 20s backoff
            print(f"  {url.split('?')[0]} slow/failed ({e}); retry {attempt}/{retries - 1} in {wait}s…")
            time.sleep(wait)


def get_token(key):
    j = http_get(TOKEN_URL, {"AccessKey": key, "User-Agent": UA})
    if j.get("Status") != "Success" or not j.get("Result"):
        sys.exit(f"Token request failed: {j}")
    return j["Result"]


def pull_transactions(key, token):
    recs = []
    for b in range(1, 5):
        try:
            j = http_get(DATA_URL.format(batch=b), {"AccessKey": key, "Token": token, "User-Agent": UA})
        except urllib.error.HTTPError as e:
            print(f"  batch {b}: HTTP {e.code} {e.reason}"); continue
        if j.get("Status") != "Success":
            print(f"  batch {b} warning: {j.get('Message')}"); continue
        got = j.get("Result", [])
        recs += got
        print(f"  batch {b}: {len(got)} project records")
    return recs


def recent(cd):
    try:
        mm, yy = int(cd[:2]), 2000 + int(cd[2:])
        d, t = date(yy, mm, 1), date.today()
        return (t.year - d.year) * 12 + (t.month - d.month) <= MONTHS_BACK
    except Exception:
        return False


def flatten(recs):
    out = []
    for p in recs:
        seg  = (p.get("marketSegment") or "").upper()
        proj = (p.get("project") or "").upper().strip()
        for t in p.get("transaction", []):
            try:
                area  = float(t.get("area", 0))
                price = float(t.get("price", 0))
            except (TypeError, ValueError):
                continue
            if area <= 0 or price <= 0:
                continue
            out.append(dict(project=proj, seg=seg, area=area, price=price,
                            tos=str(t.get("typeOfSale", "")),     # 1 new sale, 2 sub-sale, 3 resale
                            tenure=(t.get("tenure") or ""),       # e.g. "99 yrs lease commencing from 2015" or "Freehold"
                            ptype=(t.get("propertyType") or ""), cd=t.get("contractDate", "")))
    return out


def remaining_lease(tenure):
    """Years of lease left. Freehold/999-yr -> effectively unlimited; unparseable -> kept (not excluded)."""
    if not tenure:
        return 999
    t = tenure.lower()
    if "freehold" in t:
        return 999
    m = re.search(r'(\d+)\s*yr.*?from\s*(\d{4})', t)
    if m:
        length, start = int(m.group(1)), int(m.group(2))
        if length >= 900:
            return 999
        return start + length - date.today().year
    m2 = re.search(r'(\d+)\s*yr', t)
    if m2 and int(m2.group(1)) >= 900:
        return 999
    return 999


def appreciation(tx_priv):
    """Annualised growth of median PSF across the full transaction span (CAGR), as a %."""
    by_year = {}
    for t in tx_priv:
        try:
            yy = 2000 + int(t["cd"][2:])
        except Exception:
            continue
        by_year.setdefault(yy, []).append(t["price"] / (t["area"] * SQM_TO_SQFT))
    yrs = sorted(by_year)
    if len(yrs) < 2:
        return None
    y0, y1 = yrs[0], yrs[-1]
    p0, p1, n = median(by_year[y0]), median(by_year[y1]), (y1 - y0)
    if p0 <= 0 or n <= 0:
        return None
    return round(((p1 / p0) ** (1 / n) - 1) * 100, 1)


def percentile(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * p
    f = int(k); c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


# Floor-area bands (sqm) -> bedroom label, for the resale price matrix.
BED_BANDS = [("1BR", 35, 55), ("2BR", 55, 80), ("3BR", 80, 105), ("4BR", 105, 150)]


def bedroom(area):
    for name, lo, hi in BED_BANDS:
        if lo <= area < hi:
            return name
    return None


def _matrix(prices_by_region):
    return {reg: {b: {"p": (round(median(v) / 1000) * 1000 if v else None), "n": len(v)}
                  for b, v in beds.items()} for reg, beds in prices_by_region.items()}


def compute(tx):
    # Both tables are market-wide URA transactions, grouped by URA market segment (OCR/RCR/CCR) and bedroom band.
    tx = [t for t in tx if t["ptype"] in PRIVATE_TYPES and recent(t["cd"])]

    resale = {reg: {b[0]: [] for b in BED_BANDS} for reg in ("OCR", "RCR", "CCR")}   # market-wide resale
    newl   = {reg: {b[0]: [] for b in BED_BANDS} for reg in ("OCR", "RCR", "CCR")}   # market-wide new launch
    psf    = {"OCR": [], "RCR": [], "CCR": []}
    for t in tx:
        b = bedroom(t["area"])
        if t["seg"] not in resale or not b:
            continue
        if remaining_lease(t["tenure"]) < MIN_LEASE_YEARS:     # 70+ years lease remaining (freehold qualifies)
            continue
        if t["tos"] == "1":          # new sale
            newl[t["seg"]][b].append(t["price"])
        elif t["tos"] == "3":        # resale
            resale[t["seg"]][b].append(t["price"])
            psf[t["seg"]].append(t["price"] / (t["area"] * SQM_TO_SQFT))

    psf_avg = {k: (round(percentile(v, ENTRY_PCTILE) / 10) * 10 if v else None) for k, v in psf.items()}
    return _matrix(resale), _matrix(newl), psf_avg, len(tx)


def inject_bedmatrix(html, data, name):
    def cell(c):
        return "{p:%s,n:%d}" % ("null" if c["p"] is None else str(int(c["p"])), c["n"])
    rows = []
    for reg in ("OCR", "RCR", "CCR"):
        cells = ",".join('"%s":%s' % (b, cell(data.get(reg, {}).get(b, {"p": None, "n": 0})))
                         for b, _, _ in BED_BANDS)
        rows.append("  %s:{%s}" % (reg, cells))
    block = ("/* %s_START — auto-generated by ura_update.py %s */\nconst %s={\n%s\n};\n/* %s_END */"
             % (name, datetime.now().strftime("%Y-%m-%d"), name, ",\n".join(rows), name))
    new, n = re.subn(r'/\* %s_START.*?/\* %s_END \*/' % (name, name), lambda _: block, html, count=1, flags=re.S)
    return new, n > 0


def main():
    key = read_key()

    print("Requesting token…");      token = get_token(key)
    print("Pulling transactions…");  recs = pull_transactions(key, token)
    tx = flatten(recs)
    print(f"Flattened {len(tx)} transaction lines")

    if not os.path.exists(CALC_HTML):
        sys.exit("Decoupling_Calculator.html not found next to this script.")
    html = open(CALC_HTML, encoding="utf-8").read()

    matrix, newlaunch, psf, nused = compute(tx)
    appr = appreciation([t for t in tx if t["ptype"] in PRIVATE_TYPES])    # full transaction span
    print(f"Using {nused} recent private transactions (last {MONTHS_BACK} months)")
    for title, mx in (("Resale (market-wide)", matrix), ("New launch (market-wide)", newlaunch)):
        print(f"  {title} — region x bedroom:")
        for reg in ("OCR", "RCR", "CCR"):
            cells = "  ".join(f"{b}:{('$'+format(mx[reg][b]['p'],',')) if mx[reg][b]['p'] else '—':>11}({mx[reg][b]['n']})" for b, _, _ in BED_BANDS)
            print(f"    {reg}  {cells}")
    print("  Entry PSF / region (info only):", psf)
    print("  Annual appreciation (info only):", f"{appr}%/yr (URA, full transaction span)" if appr is not None else "n/a")

    html, ok1 = inject_bedmatrix(html, matrix, "MATRIX")
    html, ok2 = inject_bedmatrix(html, newlaunch, "NEWLAUNCH")
    print("Resale matrix:", "updated" if ok1 else "MARKERS NOT FOUND", "| New-launch matrix:", "updated" if ok2 else "MARKERS NOT FOUND")
    if not (ok1 and ok2):
        sys.exit("Matrix markers not found in Decoupling_Calculator.html — aborting without writing.")

    open(CALC_HTML, "w", encoding="utf-8").write(html)
    print(f"Updated resale + new-launch matrices at {datetime.now():%Y-%m-%d %H:%M}.")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP error: {e.code} {e.reason}")
    except urllib.error.URLError as e:
        sys.exit(f"Network error: {e.reason}")
    except Exception as e:
        sys.exit(f"Error: {e}")
