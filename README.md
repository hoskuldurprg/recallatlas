# Recall Atlas

One-page site listing official recalls from the US, Canada, the UK and the EU,
filterable by country, category and search. A crawler refreshes the data every
6 hours; the page is plain static HTML, so hosting is free.

## Files
| File | What it does |
|---|---|
| `template.html` | The page design and script. Edit this, not the generated pages. |
| `build_site.py` | Builds `index.html`, country pages (`/us/`, `/de/` …), product-type pages (`/recalls/food/`, `/us/food/` …), common-search pages (`/recalls/car-seats/` …), `sitemap.xml` and `robots.txt`. Edit `TOPICS` there to add search pages. |
| `index.html`, `<country>/index.html` | Generated pages. Each has its newest 40 recalls in the HTML for search engines. |
| `data/recalls.json` | The recall data, written by the crawler. |
| `crawl.py` | Fetches all sources and rewrites `data/recalls.json`. |
| `.github/workflows/crawl.yml` | Every 6 hours: runs the crawler, rebuilds the pages, commits. |
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
python build_site.py            # rebuild pages
python -m http.server 8000      # open http://localhost:8000
```

## Sources
- US: CPSC (saferproducts.gov API), FDA food/drug/device enforcement (api.fda.gov),
  NHTSA vehicles/car seats (data.transportation.gov dataset 6axg-epim), USDA FSIS meat & poultry (fsis.usda.gov API)
- UK: OPSS product safety alerts (gov.uk search API), FSA food alerts (data.food.gov.uk)
- Canada: Health Canada, CFIA and Transport Canada (recalls-rappels.canada.ca open data)
- EU/EEA: Safety Gate (ec.europa.eu public API). The EU source is the site's own
  public API rather than a documented one, so it could change without notice.
  If it breaks, the crawler keeps the previous EU rows and the other sources still update.
- EU/EEA food: RASFF Window consumer notifications (per country where the product was sold)

## Not yet included
- Australia (ACCC), New Zealand
- Email alerts, ads
