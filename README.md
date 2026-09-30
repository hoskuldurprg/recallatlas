# Recall Atlas

One-page site listing official recalls from the US, Canada, the UK and the EU,
filterable by country, category and search. A crawler refreshes the data every
6 hours; the page is plain static HTML, so hosting is free.

## Files
| File | What it does |
|---|---|
| `index.html` | The website. Loads `data/recalls.json`. |
| `data/recalls.json` | The recall data, written by the crawler. |
| `crawl.py` | Fetches all sources and rewrites `data/recalls.json`. |
| `.github/workflows/crawl.yml` | Runs the crawler every 6 hours on GitHub. |
| `CNAME` | Tells GitHub Pages to serve the site on recallatlas.org. |

## Hosting (GitHub Pages + recallatlas.org)
1. Repo must be **public** (free GitHub Pages needs it).
2. **Settings → Pages**: Source *Deploy from a branch*, branch `main`, folder `/ (root)`.
   Custom domain `recallatlas.org` (the `CNAME` file sets this), then tick *Enforce HTTPS* once it's offered.
3. **Settings → Actions → General**: Workflow permissions *Read and write*.
4. **Actions → Update recalls → Run workflow** fetches live data. After that it runs every 6 hours.
5. DNS at your registrar for `recallatlas.org`:
   - `A` records for `@`: 185.199.108.153, 185.199.109.153, 185.199.110.153, 185.199.111.153
   - `CNAME` for `www` → `hoskuldurprg.github.io`

## Run locally
```
pip install -r requirements.txt
python crawl.py                 # refresh data
python -m http.server 8000      # open http://localhost:8000
```

## Sources
- US: CPSC (saferproducts.gov API), FDA food/drug/device enforcement (api.fda.gov)
- UK: OPSS product safety alerts (gov.uk search API), FSA food alerts (data.food.gov.uk)
- Canada: Health Canada, CFIA and Transport Canada (recalls-rappels.canada.ca open data)
- EU/EEA: Safety Gate (ec.europa.eu public API). The EU source is the site's own
  public API rather than a documented one, so it could change without notice.
  If it breaks, the crawler keeps the previous EU rows and the other sources still update.

## Not yet included
- US USDA meat/poultry recalls (FSIS API) and NHTSA vehicle recalls
- EU food alerts (RASFF), Australia (ACCC)
- Per-country pages (/us, /de …) for search engines, email alerts, ads
