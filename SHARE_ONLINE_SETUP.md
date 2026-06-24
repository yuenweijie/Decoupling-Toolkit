# Share the calculator with your team — one always-current link

This hosts the calculator online for free and refreshes the URA figures **daily in the cloud**,
so your teammates just open a link and always see the latest. Your Mac doesn't need to be on,
and your URA key stays private (stored encrypted in GitHub, never in the file).

You do this **once**. Budget ~20 minutes.

---

## What you'll end up with
- A web link like `https://YOURNAME.github.io/decoupling-calculator/` to send your team.
- A daily cloud job (7:30pm SGT) that pulls URA, refreshes prices/appreciation, and republishes.

## Files already prepared in this folder
- `Decoupling_Calculator.html` — the calculator.
- `ura_update.py`, `ura_projects.json` — the updater + your project shortlist.
- `.github/workflows/update-benchmarks.yml` — the daily cloud schedule.
- `.gitignore` — keeps `ura_key.txt` (your key) OUT of the upload.

---

## Step 1 — Create a free GitHub account
Go to https://github.com and sign up (free). Verify your email.

## Step 2 — Create a new repository
1. Click the **+** (top-right) → **New repository**.
2. Name it e.g. `decoupling-calculator`. Set it to **Public** (required for free Pages) — note: the HTML is public, but your key is NOT in it.
3. Click **Create repository**.

## Step 3 — Upload these files
On the new repo page: **Add file → Upload files**. Drag in everything from this folder
**except `ura_key.txt`** (the `.gitignore` also protects it). Make sure the `.github` folder is
included (it holds the schedule). Click **Commit changes**.

> Tip: if the `.github` folder is hard to drag, use **Add file → Create new file**, type
> `.github/workflows/update-benchmarks.yml` as the name, and paste in the contents of that file.

## Step 4 — Add your URA key as an encrypted secret
1. In the repo: **Settings → Secrets and variables → Actions → New repository secret**.
2. Name: `URA_ACCESS_KEY`  ·  Value: paste your URA Access Key.  ·  **Add secret**.

This is the secure home for the key — it's encrypted and never shown again, not even to you.

## Step 5 — Turn on the website (GitHub Pages)
1. **Settings → Pages**.
2. Under **Source**, choose **Deploy from a branch**; Branch = **main**, folder = **/ (root)**. Save.
3. After a minute, the page URL appears at the top of the Pages settings — that's your team link
   (ends in `/index.html` or just `/`).

## Step 6 — Run it once to confirm
1. **Actions** tab → **Update URA benchmarks** → **Run workflow**.
2. Wait ~1 minute, then open your Pages link. You should see the live calculator.

Done. From now on it self-updates every day, and anyone with the link always gets the latest.

---

## Day-to-day
- **Edit your project shortlist:** change `ura_projects.json` in the repo (pencil icon → edit → commit).
  The next daily run (or a manual run in the Actions tab) refreshes prices for the new list.
- **Change the appreciation rate:** edit `APPR_OVERRIDE` near the top of `ura_update.py` (currently 3.5).
- **Share:** send teammates the Pages link. They bookmark it — no install, always current.

## Honest limits
- The page is **public** (anyone with the link can view). That's normal for a marketing/advisory tool,
  but don't put anything confidential in the HTML. Your key is safe (encrypted secret, never in the file).
- GitHub's free scheduler is best-effort and can lag the exact minute; the daily window is fine for this.
- URA data refreshes Tue/Fri — daily runs in between simply re-confirm the same figures.
