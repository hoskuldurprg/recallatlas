#!/usr/bin/env python3
"""Builds the static site from template.html + data/recalls.json:
  index.html            all recalls
  <country>/index.html  one page per country (us, ca, uk, eu, de, fr, ...)
  sitemap.xml, robots.txt
Each page ships with its newest recalls already in the HTML (for search engines);
the script then loads data/recalls.json for filtering and search.
Run after crawl.py:  python build_site.py
"""
import html, json
from pathlib import Path
from crawl import EU_NAMES

ROOT = Path(__file__).parent
SITE = "https://recallatlas.org"
data = json.loads((ROOT / "data" / "recalls.json").read_text())
tpl = (ROOT / "template.html").read_text()
split = tpl.index('<div class="wrap">')
head_tpl, body_tpl = tpl[:split], tpl[split:]

NAMES = {"US": "United States", "CA": "Canada", "GB": "United Kingdom", "EU": "the EU & EEA", **EU_NAMES}
CATS = {"food": "Food & drink", "kids": "Toys & kids", "electrical": "Electrical", "home": "Home & garden",
        "sports": "Sports & outdoor", "tools": "Tools & DIY", "vehicles": "Vehicles", "medical": "Drugs & medical",
        "cosmetics": "Cosmetics & chemicals", "apparel": "Clothing & jewellery", "other": "Other"}
SOURCES_BY_REGION = {
    "US": "the CPSC, FDA, NHTSA and USDA", "CA": "Health Canada, the CFIA and Transport Canada",
    "GB": "the Office for Product Safety and Standards and the Food Standards Agency",
    "EU": "the EU Safety Gate and RASFF food alerts"}
PRERENDER = 40
esc = lambda s: html.escape(str(s or ""), quote=True)
slug = lambda c: "" if c == "all" else "uk" if c == "GB" else c.lower()


def matches(r, c):
    if c == "all": return True
    if c == "EU": return r.get("region") == "EU"
    return r["country"] == c or c in (r.get("countries") or [])


def sev_class(s):
    s = (s or "").lower()
    if any(k in s for k in ["class i ", "class 1", "type i ", "serious", "death", "electric shock", "fire", "drowning",
                            "strangulation", "do not drive", "park outside"]) or s.endswith("class i") or s.endswith("type i"):
        return "high"
    if any(k in s for k in ["class ii", "class 2", "type ii", "chemical", "choking", "injur", "burn"]): return "mid"
    return ""


def render_rows(rows):
    out, last = [], ""
    for r in rows:
        if r["date"] != last:
            out.append(f'<li class="day">{r["date"]}</li>'); last = r["date"]
        cc = "UK" if r["country"] == "GB" else r["country"]
        sev = f'<span class="tag {sev_class(r["severity"] + " " + r["hazard"])}">{esc(r["severity"])}</span>' if r.get("severity") else ""
        by = f' · reported by {esc(r["countryName"])}' if r.get("region") == "EU" else ""
        extra = "".join(f"<span>{esc(r[k])}</span>" for k in ("brand", "units") if r.get(k))
        out.append(
            f'<li class="item"><div class="cc" title="{esc(r["countryName"])}">{cc}<small>{"EU" if r.get("region") == "EU" else ""}</small></div>'
            f'<div class="body"><div class="tags"><span class="tag cat">{CATS.get(r["category"], "Other")}</span>{sev}</div>'
            f'<h3><a href="{esc(r["url"])}" target="_blank" rel="noopener">{esc(r["title"])}</a></h3>'
            + (f'<p class="hz">{esc(r["hazard"])}</p>' if r.get("hazard") else "")
            + f'<div class="src"><span>{esc(r["source"])}{by}</span>{extra}'
              f'<a href="{esc(r["url"])}" target="_blank" rel="noopener">Official notice →</a></div></div></li>')
    return "\n".join(out)


def page(code):
    rows = [r for r in data["recalls"] if matches(r, code)]
    n = len(rows)
    if code == "all":
        title = "Recall Atlas: product, food and vehicle recalls in one list"
        desc = (f"{data['count']} official product, food, drug and vehicle recalls from the US, Canada, the UK and Europe, "
                "searchable by country. Updated every 6 hours.")
        h1, h2 = "Is anything you own recalled?", "All recalls"
        lede = ("Official product, food, drug and vehicle recalls from the US, Canada, the UK and 30 European countries, "
                "in one list. Pick your country, then search by product or brand.")
    else:
        name = NAMES[code]
        region = code if code in SOURCES_BY_REGION else "EU"
        title = f"Product recalls in {name} | Recall Atlas"
        desc = (f"{n} current product, food and safety recalls affecting {name}, from {SOURCES_BY_REGION[region]}. "
                "Updated every 6 hours.")
        h1, h2 = f"Recalls in {name}", f"Recalls in {name}"
        lede = (f"Official recalls and safety alerts for {name} from {SOURCES_BY_REGION[region]}, "
                "updated every 6 hours. Search by product, brand or hazard.")
    url = f"{SITE}/{slug(code)}/" if code != "all" else f"{SITE}/"
    head = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
{head_tpl}</head>
<body>
"""
    body = (body_tpl.replace("{{H1}}", esc(h1)).replace("{{H2}}", esc(h2)).replace("{{LEDE}}", esc(lede))
            .replace("{{PRERENDER}}", render_rows(rows[:PRERENDER]))
            .replace("{{PRESET}}", "" if code == "all" else code)
            .replace("{{NAMES}}", json.dumps({k: (v if k != "EU" else "all EU & EEA countries") for k, v in NAMES.items()}, ensure_ascii=False)))
    return head + body + "</body>\n</html>\n"


def main():
    codes = ["all", "US", "CA", "GB", "EU"] + sorted(EU_NAMES)
    urls = []
    for c in codes:
        out = ROOT / "index.html" if c == "all" else ROOT / slug(c) / "index.html"
        out.parent.mkdir(exist_ok=True)
        out.write_text(page(c))
        urls.append(f"{SITE}/{slug(c)}/" if c != "all" else f"{SITE}/")
    lastmod = data["updated"][:10]
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{u}</loc><lastmod>{lastmod}</lastmod><changefreq>daily</changefreq></url>\n" for u in urls)
        + "</urlset>\n")
    (ROOT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    print(f"built {len(urls)} pages")


if __name__ == "__main__":
    main()
