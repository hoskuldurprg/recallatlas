#!/usr/bin/env python3
"""Builds the static site from template.html + data/recalls.json:
  index.html                    all recalls
  <country>/index.html          one page per country (us, ca, uk, eu, de, fr, ...)
  recalls/<type>/index.html     product types (food, toys-kids, ...) and common searches (car-seats, ...)
  <region>/<type>/index.html    product type per region (us/food, uk/electrical, ...) when it has 5+ recalls
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


CATSLUG = {"food": "food", "kids": "toys-kids", "electrical": "electrical", "home": "home-garden",
           "sports": "sports-outdoor", "tools": "tools-diy", "vehicles": "vehicles", "medical": "drugs-medical",
           "cosmetics": "cosmetics-chemicals", "apparel": "clothing-jewellery"}
# Topic pages: evergreen searches like "car seat recalls". Matched on whole words in title/hazard/product.
TOPICS = [
    ("car-seats", "Car seat", ["car seat", "child seat", "booster seat", "child restraint"]),
    ("baby-products", "Baby product", ["baby", "babies", "infant", "crib", "cot", "bassinet", "stroller", "pram",
                                       "pushchair", "high chair", "teether", "pacifier", "baby sleeper"]),
    ("power-banks", "Power bank", ["power bank", "power banks", "powerbank", "portable charger", "power station"]),
    ("e-bikes-scooters", "E-bike and e-scooter", ["e-bike", "e-bikes", "ebike", "electric bike", "electric bicycle",
                                                   "e-scooter", "electric scooter"]),
    ("airbags", "Airbag", ["air bag", "air bags", "airbag", "airbags"]),
    ("batteries", "Battery", ["lithium", "li-ion", "button cell", "coin cell", "battery", "batteries"]),
    ("chargers", "Charger and adapter", ["charger", "chargers", "adapter", "adaptor", "power supply"]),
    ("heaters", "Heater and electric blanket", ["heater", "heaters", "heating pad", "heated blanket", "electric blanket"]),
    ("mattresses", "Mattress", ["mattress", "mattresses"]),
    ("furniture-tip-over", "Furniture tip-over", ["tip-over", "tip over", "dresser", "dressers", "chest of drawers", "wardrobe"]),
    ("magnets", "Magnet", ["magnet", "magnets", "magnetic"]),
    ("helmets", "Helmet", ["helmet", "helmets"]),
    ("salmonella", "Salmonella", ["salmonella"]),
    ("listeria", "Listeria", ["listeria"]),
    ("e-coli", "E. coli", ["e. coli", "e.coli", "stec", "escherichia coli"]),
    ("food-allergens", "Food allergen", ["undeclared", "allergen", "allergens", "allergy"]),
    ("choking-hazard", "Choking hazard", ["choking", "small parts"]),
    ("fire-hazard", "Fire hazard", ["fire hazard", "risk of fire", "fire and burn", "overheat", "overheating", "ignite"]),
    ("e-cigarettes", "E-cigarette", ["e-cigarette", "e-cigarettes", "vape", "vapes", "nicotine"]),
    ("tattoo-inks", "Tattoo ink", ["tattoo"]),
]
REGION_CODES = ["US", "CA", "GB", "EU"]
MIN_COUNTRY_CAT = 5
import re as _re
topic_rx = lambda words: _re.compile(r"\b(" + "|".join(_re.escape(w) for w in words) + ")", _re.I)


def select(code="all", cat=None, topic=None):
    rx = topic_rx(topic[2]) if topic else None
    return [r for r in data["recalls"] if matches(r, code) and (not cat or r["category"] == cat)
            and (not rx or rx.search(f'{r["title"]} {r["hazard"]} {r.get("product", "")}'))]


def page_path(code="all", cat=None, topic=None):
    if topic: return f"/recalls/{topic[0]}/"
    if cat: return f"/recalls/{CATSLUG[cat]}/" if code == "all" else f"/{slug(code)}/{CATSLUG[cat]}/"
    return "/" if code == "all" else f"/{slug(code)}/"


def browse_html(country_cat_pages):
    cats = "".join(f'<li><a href="/recalls/{v}/">{CATS[k]}</a></li>' for k, v in CATSLUG.items())
    tops = "".join(f'<li><a href="/recalls/{t[0]}/">{t[1]} recalls</a></li>' for t in TOPICS)
    ctry = "".join(f'<li><a href="/{slug(c)}/">{NAMES[c] if c != "EU" else "EU & EEA"}</a></li>'
                   for c in ["US", "CA", "GB", "EU", "DE", "FR", "IT", "ES", "NL", "SE", "PL", "IE"])
    return (f'<div class="browse"><div><h4>By country</h4><ul>{ctry}</ul></div>'
            f'<div><h4>By product type</h4><ul>{cats}</ul></div>'
            f'<div><h4>Common searches</h4><ul>{tops}</ul></div></div>')


def page(code="all", cat=None, topic=None, pages=(), browse=""):
    rows = select(code, cat, topic)
    n = len(rows)
    name = ("the " if code in ("US", "GB", "NL") else "") + NAMES.get(code, "")
    where = "" if code == "all" else f" in {name}"
    region = code if code in SOURCES_BY_REGION else "EU"
    if topic:
        what = f"{topic[1]} recalls"
        title = f"{what}: latest official recalls | Recall Atlas"
        desc = (f"{n} current {topic[1].lower()} recalls and safety alerts from the US, Canada, the UK and Europe, "
                "from official government sources. Updated every 6 hours.")
        h1 = what
        lede = (f"The latest official {topic[1].lower()} recalls from the US, Canada, the UK and Europe, "
                "updated every 6 hours. Pick your country to narrow the list.")
    elif cat:
        what = f"{CATS[cat]} recalls"
        title = f"{what}{where} | Recall Atlas"
        src = SOURCES_BY_REGION[region] if code != "all" else "government agencies in the US, Canada, the UK and Europe"
        desc = f"{n} current {CATS[cat].lower()} recalls{where}, from {src}. Updated every 6 hours."
        h1 = what + where
        lede = f"Official {CATS[cat].lower()} recalls{where} from {src}, updated every 6 hours."
    elif code == "all":
        title = "Recall Atlas: product, food and vehicle recalls in one list"
        desc = (f"{data['count']} official product, food, drug and vehicle recalls from the US, Canada, the UK and Europe, "
                "searchable by country. Updated every 6 hours.")
        h1 = "Is anything you own recalled?"
        lede = ("Official product, food, drug and vehicle recalls from the US, Canada, the UK and 30 European countries, "
                "in one list. Pick your country, then search by product or brand.")
    else:
        title = f"Product recalls in {name} | Recall Atlas"
        desc = (f"{n} current product, food and safety recalls affecting {name}, from {SOURCES_BY_REGION[region]}. "
                "Updated every 6 hours.")
        h1 = f"Recalls in {name}"
        lede = (f"Official recalls and safety alerts for {name} from {SOURCES_BY_REGION[region]}, "
                "updated every 6 hours. Search by product, brand or hazard.")
    h2 = h1 if not (code == "all" and not cat and not topic) else "All recalls"
    url = SITE + page_path(code, cat, topic)
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
    topic_js = json.dumps({"name": topic[1], "words": topic[2]}) if topic else "null"
    body = (body_tpl.replace("{{H1}}", esc(h1)).replace("{{H2}}", esc(h2)).replace("{{LEDE}}", esc(lede))
            .replace("{{PRERENDER}}", render_rows(rows[:PRERENDER]))
            .replace("{{PRESET}}", "" if code == "all" else code)
            .replace("{{PCAT}}", cat or "").replace("{{TOPIC}}", topic_js)
            .replace("{{PAGES}}", json.dumps(sorted(pages)))
            .replace("{{BROWSE}}", browse)
            .replace("{{NAMES}}", json.dumps({k: (v if k != "EU" else "all EU & EEA countries") for k, v in NAMES.items()}, ensure_ascii=False)))
    return head + body + "</body>\n</html>\n"


def write(path, html_text):
    out = ROOT / path.strip("/") / "index.html" if path != "/" else ROOT / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_text)


def main():
    specs = [("all", None, None), *[(c, None, None) for c in ["US", "CA", "GB", "EU"] + sorted(EU_NAMES)]]
    specs += [("all", c, None) for c in CATSLUG]
    specs += [(code, c, None) for code in REGION_CODES for c in CATSLUG if len(select(code, c)) >= MIN_COUNTRY_CAT]
    specs += [("all", None, t) for t in TOPICS]
    cat_pages = [page_path(*s) for s in specs if s[1]]
    browse = browse_html(cat_pages)
    urls = []
    for spec in specs:
        path = page_path(*spec)
        write(path, page(*spec, pages=cat_pages, browse=browse))
        urls.append(SITE + path)
    # drop country x category pages that fell below the threshold since the last build
    for code in REGION_CODES:
        for c, cs in CATSLUG.items():
            f = ROOT / slug(code) / cs / "index.html"
            if f.exists() and f"/{slug(code)}/{cs}/" not in cat_pages:
                f.unlink(); f.parent.rmdir()
    lastmod = data["updated"][:10]
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{u}</loc><lastmod>{lastmod}</lastmod><changefreq>daily</changefreq></url>\n" for u in urls)
        + "</urlset>\n")
    (ROOT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    print(f"built {len(urls)} pages")


if __name__ == "__main__":
    main()
