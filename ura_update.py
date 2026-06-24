#!/usr/bin/env python3
"""
URA benchmark updater for the Decoupling Calculator.

What it does
------------
1. Reads your URA Access Key from `ura_key.txt` (same folder) — never hard-coded.
2. Requests a daily Token from the URA Data Service.
3. Pulls the latest private residential transactions (PMI_Resi_Transaction, 4 batches).
4. For every project in your curated `ura_projects.json` shortlist, computes a realistic
   ENTRY price (20th-percentile of recent transacted prices) and regenerates the
   `const PROJECTS = [...]` shortlist embedded in Decoupling_Calculator.html.
5. Also refreshes the OCR/RCR/CCR PSF guides (psfOCR/psfRCR/psfCCR) used by the size table.

Run it manually, or schedule it Tue/Fri — see URA_UPDATE_SETUP.md.

NOTE: parsing follows URA's documented field names. If a first run looks empty/odd,
paste the console output back and it can be tuned in minutes.
"""

import json, re, sys, os, ssl, urllib.request, urllib.error
from datetime import date, datetime
from statistics import median

HERE          = os.path.dirname(os.path.abspath(__file__))
KEY_FILE      = os.path.join(HERE, "ura_key.txt")
PROJECTS_FILE = os.path.join(HERE, "ura_projects.json")
CALC_HTML     = os.path.join(HERE, "Decoupling_Calculator.html")

MONTHS_BACK   = 12         # look-back window for transactions
ENTRY_PCTILE  = 0.20       # 20th percentile of a project's recent prices = realistic entry unit
APPR_OVERRIDE = 3.5        # appreciation % written to the calculator. Set to None to use the URA-computed CAGR instead.
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


def http_get(url, headers):
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=90, context=ctx) as r:
        raw = r.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")     # URA names can carry accented bytes
    return json.loads(text)


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


def existing_prices(html):
    """Parse current PROJECTS entry prices so projects with no recent data keep their last price."""
    m = re.search(r'/\* PROJECTS_START.*?(const PROJECTS=\[.*?\];).*?/\* PROJECTS_END \*/', html, re.S)
    res = {}
    if m:
        for nm, price in re.findall(r'name:"([^"]+)"[^}]*?entry:(\d+)', m.group(1)):
            res[nm.upper().strip()] = int(price)
    return res


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


def compute(tx, projects):
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


def set_field(html, el_id, text):
    """Replace the value="..." of an input (handles integers and decimals)."""
    if text is None:
        return html, False
    pat = re.compile(r'(id="' + re.escape(el_id) + r'"[^>]*?value=")[0-9.]+(")')
    new, n = pat.subn(lambda m: m.group(1) + str(text) + m.group(2), html, count=1)
    return new, n > 0


def set_field(html, el_id, text):
    """Replace the value="..." of an input (handles integers and decimals)."""
    if text is None:
        return html, False
    pat = re.compile(r'(id="' + re.escape(el_id) + r'"[^>]*?value=")[0-9.]+(")')
    new, n = pat.subn(lambda m: m.group(1) + str(text) + m.group(2), html, count=1)
    return new, n > 0


def main():
    key = read_key()

    if not os.path.exists(PROJECTS_FILE):
        sys.exit("ura_projects.json not found.")
    pj = json.load(open(PROJECTS_FILE, encoding="utf-8"))
    projects = pj.get("projects", [])
    print(f"Shortlist: {len(projects)} projects")

    print("Requesting token…");      token = get_token(key)
    print("Pulling transactions…");  recs = pull_transactions(key, token)
    tx = flatten(recs)
    print(f"Flattened {len(tx)} transaction lines")

    if not os.path.exists(CALC_HTML):
        sys.exit("Decoupling_Calculator.html not found next to this script.")
    html = open(CALC_HTML, encoding="utf-8").read()

    matrix, newlaunch, psf, nused = compute(tx, projects)
    appr = appreciation([t for t in tx if t["ptype"] in PRIVATE_TYPES])    # full 5-yr span
    print(f"Using {nused} recent private transactions (last {MONTHS_BACK} months)")
    for title, mx in (("Resale (shortlist)", matrix), ("New launch (market-wide)", newlaunch)):
        print(f"  {title} — region x bedroom:")
        for reg in ("OCR", "RCR", "CCR"):
            cells = "  ".join(f"{b}:{('$'+format(mx[reg][b]['p'],',')) if mx[reg][b]['p'] else '—':>11}({mx[reg][b]['n']})" for b, _, _ in BED_BANDS)
            print(f"    {reg}  {cells}")
    print("  PSF / region          :", psf)
    print("  Annual appreciation    :", f"{appr}%/yr (URA, full transaction span)" if appr is not None else "n/a")

    html, ok1 = inject_bedmatrix(html, matrix, "MATRIX")
    html, ok2 = inject_bedmatrix(html, newlaunch, "NEWLAUNCH")
    print("Resale matrix:", "updated" if ok1 else "MARKERS NOT FOUND", "| New-launch matrix:", "updated" if ok2 else "MARKERS NOT FOUND")
    pcount = 0
    for el, val in [("psfOCR", psf["OCR"]), ("psfRCR", psf["RCR"]), ("psfCCR", psf["CCR"])]:
        html, done = set_field(html, el, str(int(val)) if val is not None else None)
        pcount += 1 if done else 0
    rate = APPR_OVERRIDE if APPR_OVERRIDE is not None else appr
    if rate is not None:
        html, _ = set_field(html, "apprRate", f"{rate:.1f}")
        print(f"  Appreciation written   : {rate:.1f}%/yr" + (" (locked override)" if APPR_OVERRIDE is not None else " (URA-computed)"))

    open(CALC_HTML, "w", encoding="utf-8").write(html)
    print(f"Updated resale + new-launch matrices + {pcount}/3 PSF guides + appreciation rate at {datetime.now():%Y-%m-%d %H:%M}.")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP error: {e.code} {e.reason}")
    except urllib.error.URLError as e:
        sys.exit(f"Network error: {e.reason}")
    except Exception as e:
        sys.exit(f"Error: {e}")
