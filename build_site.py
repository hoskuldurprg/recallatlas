#!/usr/bin/env python3
"""Builds the static site into _site/ (deployed to GitHub Pages by the workflow).
  index.html                    all recalls (last 60 days, from data/recalls.json)
  <country>/                    one page per country (us, ca, uk, eu, de, fr, ...)
  recalls/<type>/               product types (food, toys-kids, ...) and common searches (car-seats, ...)
  <region>/<type>/              product type per region (us/food, ...) when it has 5+ recalls
  recall/<slug>/                one page per recall, for every recall in the archive (data/archive)
  brand/<slug>/, brand/         brands with 2+ recalls, and an A-Z index
  sitemap.xml (index) + sitemap-*.xml, robots.txt, IndexNow key, assets/site.css
Run after crawl.py:  python build_site.py            (add --indexnow to ping search engines about new recalls)
"""
import html, json, os, re, shutil, sys, hashlib, datetime as dt, urllib.request
from collections import defaultdict, Counter
from pathlib import Path
import crawl
from crawl import EU_NAMES

ROOT = Path(__file__).parent
OUT = ROOT / "_site"
SITE = "https://recallatlas.org"
INDEXNOW_KEY = "7c1f4e9a2b8d4c6e9f0a3b5d7e1c2a48"
DISCLAIMER = ("Recall Atlas is an independent site that collects recalls automatically from official government sources every 6 hours. The information may be incomplete, delayed or contain errors, and a product not appearing here does not mean it is safe. Always check the official notice and contact the manufacturer or seller before acting. Recall Atlas is not affiliated with any government agency and accepts no liability for decisions made using this site. <a href=\"/disclaimer/\">Full disclaimer</a>")
KEEP = ["date", "country", "countries", "region", "countryName", "source", "title", "product", "brand", "hazard",
        "severity", "units", "category", "url", "slug"]
STATIC = ["CNAME", "favicon.svg", "favicon.ico", "apple-touch-icon.png", "og-image.png"]

data = json.loads((ROOT / "data" / "recalls.json").read_text())
archive = crawl.load_archive()
# rows in the 60-day list link to their recall page; fill slugs from the archive if the list predates them
for r in data["recalls"]:
    if not r.get("slug") and r["id"] in archive:
        r["slug"] = archive[r["id"]]["slug"]

ARCH = sorted((crawl.with_names(r) for r in archive.values()), key=lambda r: (r["date"], r["id"]), reverse=True)
_ycount = Counter(r["date"][:4] for r in ARCH)
YEARS = sorted((y for y, n in _ycount.items() if n >= 100), reverse=True)  # ignore stray old records
FIRST_DAY = min((r["date"] for r in ARCH if r["date"][:4] in YEARS), default="")
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
BRANDS = {}

tpl = (ROOT / "template.html").read_text()
CSS = tpl[tpl.index("<style>") + 7:tpl.index("</style>")].strip() + "\n"
CSS_V = hashlib.sha1(CSS.encode()).hexdigest()[:8]
tpl = tpl[:tpl.index("<style>")] + f'<link rel="stylesheet" href="/assets/site.css?v={CSS_V}">' + tpl[tpl.index("</style>") + 8:]
split = tpl.index('<div class="wrap">')
head_tpl, body_tpl = tpl[:split], tpl[split:]
CONSENT = tpl[tpl.index('<div class="consent"'):tpl.index('<script id="recall-data"')]
BRAND_A = re.search(r'<a class="brand".*?</a>', tpl, re.S).group(0)

NAMES = {"US": "United States", "CA": "Canada", "GB": "United Kingdom", "EU": "the EU & EEA", **EU_NAMES}
CATS = {"food": "Food & drink", "kids": "Toys & kids", "electrical": "Electrical", "home": "Home & garden",
        "sports": "Sports & outdoor", "tools": "Tools & DIY", "vehicles": "Vehicles", "medical": "Drugs & medical",
        "cosmetics": "Cosmetics & chemicals", "apparel": "Clothing & jewellery", "other": "Other"}
SOURCES_BY_REGION = {
    "US": "the CPSC, FDA, NHTSA and USDA", "CA": "Health Canada, the CFIA and Transport Canada",
    "GB": "the Office for Product Safety and Standards and the Food Standards Agency",
    "EU": "the EU Safety Gate and RASFF food alerts"}
AGENCY = {"CPSC": "the US Consumer Product Safety Commission", "FDA": "the US Food and Drug Administration",
          "NHTSA": "the US National Highway Traffic Safety Administration",
          "USDA FSIS": "the USDA Food Safety and Inspection Service",
          "UK OPSS": "the UK Office for Product Safety and Standards", "UK FSA": "the UK Food Standards Agency",
          "Canada": "the Government of Canada", "EU Safety Gate": "the European Commission's Safety Gate",
          "EU RASFF": "the EU Rapid Alert System for Food and Feed"}
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


rlink = lambda r: f'/recall/{r["slug"]}/' if r.get("slug") else esc(r["url"])


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
            f'<h3><a href="{rlink(r)}">{esc(r["title"])}</a></h3>'
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


def select(code="all", cat=None, topic=None, year=None):
    rx = topic_rx(topic[2]) if topic else None
    src = [r for r in ARCH if r["date"][:4] == year] if year else data["recalls"]
    return [r for r in src if matches(r, code) and (not cat or r["category"] == cat)
            and (not rx or rx.search(f'{r["title"]} {r["hazard"]} {r.get("product", "")}'))]


def page_path(code="all", cat=None, topic=None, year=None):
    y = f"{year}/" if year else ""
    if topic: return f"/recalls/{topic[0]}/{y}"
    if cat: return (f"/recalls/{CATSLUG[cat]}/" if code == "all" else f"/{slug(code)}/{CATSLUG[cat]}/") + y
    if code == "all": return f"/recalls/{y}" if year else "/"
    return f"/{slug(code)}/{y}"


def browse_html(country_cat_pages):
    cats = "".join(f'<li><a href="/recalls/{v}/">{CATS[k]}</a></li>' for k, v in CATSLUG.items())
    tops = "".join(f'<li><a href="/recalls/{t[0]}/">{t[1]} recalls</a></li>' for t in TOPICS)
    ctry = "".join(f'<li><a href="/{slug(c)}/">{NAMES[c] if c != "EU" else "EU & EEA"}</a></li>'
                   for c in ["US", "CA", "GB", "EU", "DE", "FR", "IT", "ES", "NL", "SE", "PL", "IE"])
    yrs = "".join(f'<li><a href="/recalls/{y}/">{y}</a></li>' for y in YEARS)
    return (f'<div class="browse"><div><h4>By country</h4><ul>{ctry}</ul></div>'
            f'<div><h4>By product type</h4><ul>{cats}</ul></div>'
            f'<div><h4>Common searches</h4><ul>{tops}</ul></div>'
            f'<div><h4>By year</h4><ul>{yrs}<li><a href="/brand/">All brands</a></li></ul></div></div>')


def country_label(c):
    return "EU & EEA" if c == "EU" else NAMES.get(c, c)


def head_html(title, desc, url, kind="website", crumbs=None, image=None, extra_ld=None):
    ld = []
    if crumbs:
        ld.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": SITE + p} for i, (n, p) in enumerate(crumbs)]})
    if extra_ld: ld.append(extra_ld)
    ld_html = "".join('<script type="application/ld+json">' + json.dumps(x, ensure_ascii=False).replace("</", "<\\/") + "</script>\n" for x in ld)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="{kind}">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:image" content="{SITE}/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
{ld_html}{head_tpl}</head>
<body>
"""


def year_note(year):
    if year == FIRST_DAY[:4] and FIRST_DAY[5:7] != "01":
        return f" (records start {MON[int(FIRST_DAY[5:7]) - 1]} {year})"
    if year == YEARS[0]: return " so far"
    return ""


def stats_html(rows, code, cat, year):
    months = [0] * 12
    for r in rows: months[int(r["date"][5:7]) - 1] += 1
    mx = max(months) or 1
    bars = "".join(f'<span style="height:{max(3, round(m / mx * 100))}%" title="{MON[i]} {year}: {m}"></span>'
                   for i, m in enumerate(months))
    bc = Counter(r["_brand"] for r in rows if r.get("_brand")).most_common(6)
    brands = "".join(f'<li><a href="/brand/{k}/">{esc(BRANDS[k][0])}</a><span>{n}</span></li>' for k, n in bc)
    out = (f'<section class="ystats"><div><h4>Recalls in {year}</h4><div class="big">{len(rows):,}</div>'
           f'<p class="note">{esc(year_note(year).strip(" ()").capitalize())}</p></div>'
           f'<div><h4>By month</h4><div class="months">{bars}</div>'
           f'<div class="mlab"><span>Jan</span><span>Jun</span><span>Dec</span></div></div>')
    if brands: out += f'<div><h4>Most recalled brands</h4><ol>{brands}</ol></div>'
    if not cat:
        cc = Counter(r["category"] for r in rows).most_common(6)
        def link(c):
            pth = page_path(code if code in REGION_CODES else "all", c, None, year) if c in CATSLUG else None
            return f'<a href="{pth}">{CATS[c]}</a>' if pth in BUILT else CATS.get(c, "Other")
        out += "<div><h4>By product type</h4><ol>" + "".join(f"<li>{link(c)}<span>{n}</span></li>" for c, n in cc) + "</ol></div>"
    return out + "</section>"


def page(code="all", cat=None, topic=None, year=None, pages=(), browse=""):
    rows = select(code, cat, topic, year)
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
    if year:
        what = (f"{topic[1]} recalls" if topic else f"{CATS[cat]} recalls" if cat else "Recalls")
        src = SOURCES_BY_REGION[region] if code != "all" else "government agencies in the US, Canada, the UK and Europe"
        h1 = f"{what}{where} in {year}" if (where or topic or cat) else f"All recalls in {year}"
        title = f"{h1} | Recall Atlas"
        desc = (f"All {n} official {what.lower()}{where} in {year}{year_note(year)}, from {src}: "
                "month by month, most recalled brands and every official notice.")
        lede = (f"{n:,} official {what.lower()}{where} reported in {year}{year_note(year)}, from {src}. "
                "Newest first. Search by product, brand or hazard.")
    h2 = h1 if (year or not (code == "all" and not cat and not topic)) else "All recalls"
    url = SITE + page_path(code, cat, topic, year)
    crumbs = [("Recall Atlas", "/")]
    if topic: crumbs.append((topic[1] + " recalls", page_path(code, cat, topic)))
    else:
        if code != "all": crumbs.append((country_label(code), page_path(code)))
        if cat: crumbs.append((CATS[cat], page_path(code, cat)))
    if year: crumbs.append((year, page_path(code, cat, topic, year)))
    head = head_html(title, desc, url, "website", crumbs if len(crumbs) > 1 else None)
    topic_js = json.dumps({"name": topic[1], "words": topic[2]}) if topic else "null"
    body = (body_tpl.replace("{{H1}}", esc(h1)).replace("{{H2}}", esc(h2)).replace("{{LEDE}}", esc(lede))
            .replace("{{PRERENDER}}", render_rows(rows[:PRERENDER]))
            .replace("{{PRESET}}", "" if code == "all" else code)
            .replace("{{PCAT}}", cat or "").replace("{{TOPIC}}", topic_js)
            .replace("{{PYEAR}}", year or "").replace("{{YEARS}}", json.dumps([int(y) for y in YEARS]))
            .replace("{{STATS}}", stats_html(rows, code, cat, year) if year else "")
            .replace("{{PAGES}}", json.dumps(sorted(pages)))
            .replace("{{BROWSE}}", browse)
            .replace("{{NAMES}}", json.dumps({k: (v if k != "EU" else "all EU & EEA countries") for k, v in NAMES.items()}, ensure_ascii=False)))
    return head + body + "</body>\n</html>\n"


# ---------- brands ----------
SUFFIX = re.compile(r"[,.]?\s+(inc|incorporated|llc|l\.l\.c|ltd|limited|co|corp|corporation|company|gmbh|s\.?a|s\.?a\.?s|"
                    r"s\.?r\.?l|b\.?v|ag|plc|pty|lp|usa|us|america|north america|of america|international)\.?$", re.I)
ALIAS = {"ford motor": "Ford", "general motors": "General Motors", "gm": "General Motors", "fca": "Chrysler", "chrysler": "Chrysler",
         "chrysler fca": "Chrysler", "fca us": "Chrysler", "jaguar land rover": "Jaguar Land Rover",
         "mercedes-benz": "Mercedes-Benz", "volkswagen group": "Volkswagen", "volkswagen": "Volkswagen",
         "toyota motor engineering & manufacturing": "Toyota", "toyota motor": "Toyota", "american honda motor": "Honda",
         "honda": "Honda", "hyundai motor": "Hyundai", "kia": "Kia", "nissan": "Nissan", "bmw of": "BMW",
         "bmw": "BMW", "subaru of": "Subaru", "mazda north american operations": "Mazda", "volvo car": "Volvo",
         "porsche cars": "Porsche", "mitsubishi motors": "Mitsubishi", "tesla": "Tesla", "rivian automotive": "Rivian",
         "harley-davidson motor": "Harley-Davidson", "paccar": "PACCAR",
         "forest river": "Forest River", "mack trucks": "Mack", "daimler truck": "Daimler Truck",
         "daimler trucks": "Daimler Truck", "blue bird body": "Blue Bird", "fiat chrysler automobiles": "Chrysler",
         "lidl us trading": "Lidl", "shein distribution": "SHEIN", "nova bus": "Nova Bus", "winnebago industries": "Winnebago", "thor motor coach": "Thor Motor Coach"}
NOT_BRANDS = {"", "unknown", "no brand", "none", "n/a", "various", "generic", "certain", "sold", "multiple",
              "original", "platinum", "wonder", "premium", "classic", "new", "home", "kids", "baby", "pro", "smart"}


def clean_brand(b):
    b = re.sub(r"\s+", " ", re.sub(r"^(updated|update \d+):\s*", "", str(b or ""), flags=re.I)).strip(" .,;:-–")
    b = re.sub(r"^the\s+", "", b, flags=re.I)
    for _ in range(4):
        b = re.sub(r"\s+\d+$", "", b)
        b = re.sub(r"\s*\([^()]*\)$", "", b) if not b.startswith("(") else b
        b = SUFFIX.sub("", b).strip(" .,")
    key = b.lower()
    if key in NOT_BRANDS or len(key) < 2 or len(key) > 60: return None, None
    if key in ALIAS: return crawl.slugify(ALIAS[key]), ALIAS[key]
    return crawl.slugify(b), b


def raw_brand(r):
    if r.get("brand"): return r["brand"]
    t = r["title"]
    if r.get("feed") in ("CPSC", "UK FSA", "USDA FSIS"):
        m = re.match(r"^(?:Updated:\s*)?(.+?)\s+(?:Recalls|recalls|is recalling|recall)\s", t)
        return m.group(1) if m else ""
    if r.get("feed") == "Canada":
        m = re.match(r"^Transport Canada Recall\s*-\s*\d+\s*-\s*(.+)$", t)
        if m: return m.group(1).title() if m.group(1).isupper() else m.group(1)
        m = re.match(r"^(?:Certain\s+)?(.+?)\s+brand\s", t)
        return m.group(1) if m and len(m.group(1)) < 50 else ""
    return ""


def brand_index(rows):
    """{brand_slug: (display name, [rows newest first])} for brands with 2+ recalls."""
    groups, names = defaultdict(list), defaultdict(Counter)
    for r in rows:
        k, name = clean_brand(raw_brand(r))
        if k:
            r["_brand"] = k
            groups[k].append(r)
            names[k][name] += 1
    out = {}
    for k, rs in groups.items():
        if len(rs) < 2: continue
        forms = names[k].most_common()
        name = next((n for n, _ in forms if not n.isupper()), forms[0][0])
        if name.isupper() and len(name) > 4: name = name.title()
        out[k] = (name, sorted(rs, key=lambda r: (r["date"], r["id"]), reverse=True))
    for r in rows:
        if r.get("_brand") not in out: r.pop("_brand", None)
    return out


# ---------- recall pages ----------
TODO = {
    "food": ["Check the product name, pack size, batch or lot code and best-before date against the official notice.",
             "If it matches, do not eat or drink it. Return it to the shop for a refund or throw it away as the notice says.",
             "If you have eaten it and feel unwell, contact a doctor or your local health service and mention the recall."],
    "vehicles": ["Check whether your vehicle is affected by entering its VIN (vehicle identification number) on the "
                 "manufacturer's or the agency's recall lookup.",
                 "Contact a dealer to book the repair. Recall repairs are normally free of charge.",
                 "If the notice says not to drive or to park outside, follow that until the repair is done."],
    "medical": ["Check the product name, strength and lot number against the official notice.",
                "Do not stop a prescribed medicine without talking to your doctor or pharmacist first.",
                "Ask the pharmacy or supplier about a replacement or refund."],
    "default": ["Check the brand, model, batch number and pictures against the official notice.",
                "If yours matches, stop using it and keep it away from children.",
                "Follow the remedy in the notice: a refund, repair or replacement from the seller or maker. "
                "Many recalls also apply to items bought online."],
}


def rec_country_path(r):
    """Breadcrumb trail for a recall: Home > Country > Category (country x category page when it exists)."""
    c = r["country"]
    region = "EU" if r.get("region") == "EU" else c
    trail = [("Recall Atlas", "/"), (country_label(c), page_path(c))]
    if r["category"] in CATSLUG:
        p = page_path(region, r["category"])
        trail.append((CATS[r["category"]], p if p in BUILT else page_path("all", r["category"])))
    return trail


def neighbours(group, r, n=6):
    i = group.index(r)
    lo = max(0, min(i - n // 2, len(group) - n - 1))
    return [x for x in group[lo:lo + n + 1] if x is not r][:n]


def facts_html(r, brands):
    cc = r["country"]
    rows = [("Date", esc(r["date"])), ("Country", esc(r.get("countryName") or cc))]
    if r.get("countries"):
        rows.append(("Also notified in", esc(", ".join(NAMES.get(x, x) for x in r["countries"] if x != cc))))
    if r.get("_brand"):
        rows.append(("Brand", f'<a href="/brand/{r["_brand"]}/">{esc(brands[r["_brand"]][0])}</a>'))
    elif r.get("brand"):
        rows.append(("Brand", esc(r["brand"])))
    for k, label in (("product", "Product"), ("severity", "Classification"), ("units", "Units")):
        if r.get(k) and not (k == "product" and r[k] == r["title"]) and not (k == "severity" and r[k].lower() == "vehicle"):
            rows.append((label, esc(r[k])))
    rows += [("Category", f'<a href="{page_path("all", r["category"]) if r["category"] in CATSLUG else "/"}">{CATS.get(r["category"], "Other")}</a>'),
             ("Source", f'<a href="{esc(r["url"])}" rel="noopener" target="_blank">{esc(r["source"])}</a>')]
    return '<dl class="facts">' + "".join(f"<dt>{a}</dt><dd>{b}</dd>" for a, b in rows) + "</dl>"


def recall_page(r, brands, by_cc, footer):
    name = r.get("countryName") or r["country"]
    t = r["title"]
    title = f"{t[:80].rstrip()}{'…' if len(t) > 80 else ''} – recall {r['date']} | Recall Atlas"
    desc = (f"{r['source']} recall, {r['date']}, {name}. "
            + (f"Hazard: {r['hazard'][:140]}. " if r.get("hazard") else "")
            + "What to do and a link to the official notice.")
    url = f"{SITE}/recall/{r['slug']}/"
    crumbs = rec_country_path(r)
    sev = f'<span class="tag {sev_class(r["severity"] + " " + r["hazard"])}">{esc(r["severity"])}</span>' if r.get("severity") else ""
    img = (f'<img class="shot" src="{esc(r["image"])}" alt="{esc(r.get("product") or t)}" loading="lazy" '
           f'referrerpolicy="no-referrer" onerror="this.remove()">') if r.get("image") else ""
    todo = TODO.get(r["category"], TODO["default"])
    parts = []
    if r.get("_brand"):
        bname, brs = brands[r["_brand"]]
        rel = neighbours(brs, r)
        if rel:
            parts.append(f'<h2>More {esc(bname)} recalls</h2><ol class="list">{render_rows(rel)}</ol>'
                         f'<a class="more-link" href="/brand/{r["_brand"]}/">All {len(brs)} {esc(bname)} recalls →</a>')
    grp = by_cc.get((r["category"], r["country"]), [])
    if len(grp) > 1:
        what = CATS.get(r["category"], "Other").lower()
        parts.append(f'<h2>Other {what} recalls in {esc(("the " if r["country"] in ("US", "GB", "NL") else "") + name)}</h2>'
                     f'<ol class="list">{render_rows(neighbours(grp, r))}</ol>'
                     f'<a class="more-link" href="{crumbs[-1][1]}">See all {esc(crumbs[-1][0].lower())} recalls →</a>')
    nav = " › ".join(f'<a href="{p}">{esc(n)}</a>' for n, p in crumbs)
    body = f"""<div class="wrap">
<header class="top slim">{BRAND_A}</header>
<nav class="crumbs" aria-label="Breadcrumb">{nav}</nav>
<article class="recall">
<div class="tags"><span class="tag cat">{CATS.get(r["category"], "Other")}</span>{sev}</div>
<h1>{esc(t)}</h1>
{f'<p class="lede">{esc(r["hazard"])}</p>' if r.get("hazard") else ""}
<a class="cta" href="{esc(r["url"])}" rel="noopener" target="_blank">Read the official notice →</a>
{img}{facts_html(r, brands)}
<p class="note">Copied automatically from {esc(AGENCY.get(r.get("feed"), r["source"]))}. Details may be shortened or out of date; the official notice is the authoritative source. <a href="/disclaimer/">Disclaimer</a></p>
<h2>What to do</h2>
<ol class="todo">{"".join(f"<li>{esc(x)}</li>" for x in todo)}</ol>
<p class="note">General guidance from Recall Atlas. The official notice from {esc(AGENCY.get(r.get("feed"), r["source"]))} has the exact models, batch codes and remedy, and it takes priority.</p>
{"".join(parts)}
</article>
</div>
{footer}{CONSENT}"""
    return head_html(title, desc, url, "article", crumbs + [(t[:60], f"/recall/{r['slug']}/")]) + body + "</body>\n</html>\n"


def footer_html(browse):
    return (f'<footer><div class="wrap">{browse}<p>{DISCLAIMER}</p><p>Visitor statistics (Google Analytics) are only collected if you accept '
            'them. <button class="linkbtn" id="privacyBtn" type="button">Change cookie settings</button></p></div></footer>\n')


def brand_page(k, name, rs, footer):
    years = f"{rs[-1]['date'][:4]}" + (f"–{rs[0]['date'][:4]}" if rs[-1]['date'][:4] != rs[0]['date'][:4] else "")
    srcs = sorted({r["source"] for r in rs})
    title = f"{name} recalls ({len(rs)}) | Recall Atlas"
    desc = (f"All {len(rs)} official {name} recalls and safety alerts ({years}) from "
            f"{', '.join(srcs[:4])}. Updated every 6 hours.")
    crumbs = [("Recall Atlas", "/"), ("Brands", "/brand/"), (name, f"/brand/{k}/")]
    nav = " › ".join(f'<a href="{p}">{esc(n)}</a>' for n, p in crumbs)
    body = f"""<div class="wrap">
<header class="top slim">{BRAND_A}</header>
<nav class="crumbs" aria-label="Breadcrumb">{nav}</nav>
<article class="recall">
<h1>{esc(name)} recalls</h1>
<p class="lede">{len(rs)} official recalls and safety alerts involving {esc(name)} since {rs[-1]['date'][:7]}, from {esc(', '.join(srcs))}. Newest first. Check the official notice for exact models and batch codes.</p>
<p class="note">This list only includes recalls Recall Atlas has collected since {esc(FIRST_DAY[:7])}. A product not listed here may still be affected; check with {esc(name)} or the relevant agency.</p>
<ol class="list">{render_rows(rs[:500])}</ol>
</article>
</div>
{footer}{CONSENT}"""
    return head_html(title, desc, f"{SITE}/brand/{k}/", "website", crumbs) + body + "</body>\n</html>\n"


def brands_index_page(brands, footer):
    items = sorted(brands.items(), key=lambda kv: kv[1][0].lower())
    lis = "".join(f'<li><a href="/brand/{k}/">{esc(n)}</a><span>{len(rs)}</span></li>' for k, (n, rs) in items)
    crumbs = [("Recall Atlas", "/"), ("Brands", "/brand/")]
    body = f"""<div class="wrap">
<header class="top slim">{BRAND_A}</header>
<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Recall Atlas</a> › <a href="/brand/">Brands</a></nav>
<article class="recall"><h1>Recalls by brand</h1>
<p class="lede">{len(items)} brands with more than one official recall. Pick a brand to see every recall in one list.</p>
<ul class="brands">{lis}</ul></article></div>
{footer}{CONSENT}"""
    return head_html("Product recalls by brand A–Z | Recall Atlas",
                     f"Recall history for {len(items)} brands, from official sources in the US, Canada, the UK and Europe.",
                     f"{SITE}/brand/", "website", crumbs) + body + "</body>\n</html>\n"


DISCLAIMER_FULL = [
    ("What this site is", "Recall Atlas is an independent website that gathers product, food, drug and vehicle recalls "
     "published by government agencies in the United States, Canada, the United Kingdom and the European Union, and shows "
     "them in one searchable list. It is not run by, endorsed by or affiliated with any of those agencies."),
    ("Information is provided as is", "Recalls are collected automatically and may be incomplete, delayed, out of date or "
     "contain errors, including errors made when copying, shortening, translating or categorising them. Product categories, "
     "brand groupings, summaries and the \"What to do\" guidance are added by Recall Atlas, are general in nature and are not "
     "part of the official notice. Information is provided without any warranty of accuracy, completeness or fitness for a "
     "particular purpose."),
    ("Always check the official notice", "The official notice from the agency, manufacturer or seller is the only authoritative "
     "source. It has the exact models, batch codes, dates and remedy. Check it, and contact the manufacturer or seller, before "
     "you act. A product not appearing on Recall Atlas does not mean it is safe or has never been recalled."),
    ("Not professional advice", "Nothing on this site is medical, legal or safety advice. If someone is unwell or injured, "
     "contact a doctor or your local emergency services. Do not stop taking a prescribed medicine without talking to a "
     "doctor or pharmacist."),
    ("Limitation of liability", "To the extent permitted by law, Recall Atlas and its operators accept no liability for any "
     "loss, damage, injury or cost arising from use of, or reliance on, the information on this site or on linked websites."),
    ("Trademarks and links", "Brand and product names belong to their owners and are used only to identify recalled products; "
     "their use does not imply any connection with Recall Atlas. Links to official notices and other websites are provided for "
     "convenience, and Recall Atlas is not responsible for their content."),
]


def disclaimer_page(footer):
    secs = "".join(f"<h2>{h}</h2><p>{esc(b)}</p>" for h, b in DISCLAIMER_FULL)
    crumbs = [("Recall Atlas", "/"), ("Disclaimer", "/disclaimer/")]
    body = f"""<div class="wrap">
<header class="top slim">{BRAND_A}</header>
<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Recall Atlas</a> › <a href="/disclaimer/">Disclaimer</a></nav>
<article class="recall prose"><h1>Disclaimer</h1>{secs}</article></div>
{footer}{CONSENT}"""
    return head_html("Disclaimer | Recall Atlas", "How Recall Atlas collects recall information and the limits of that information.",
                     f"{SITE}/disclaimer/", "website", crumbs) + body + "</body>\n</html>\n"


# ---------- output ----------
BUILT = set()


def write(path, html_text):
    out = OUT / path.strip("/") / "index.html" if path != "/" else OUT / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_text)


def sitemap(name, urls):
    (OUT / name).write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{u}</loc>{f'<lastmod>{m}</lastmod>' if m else ''}</url>\n" for u, m in urls)
        + "</urlset>\n")
    return name


def indexnow(urls):
    if not urls: return print("IndexNow: nothing new")
    body = json.dumps({"host": "recallatlas.org", "key": INDEXNOW_KEY, "keyLocation": f"{SITE}/{INDEXNOW_KEY}.txt",
                       "urlList": urls[:10000]}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            print(f"IndexNow: sent {len(urls)} URLs, HTTP {res.status}")
    except Exception as e:
        print(f"IndexNow failed: {e}", file=sys.stderr)


def main():
    global BRANDS
    if OUT.exists(): shutil.rmtree(OUT)
    OUT.mkdir()
    BRANDS = brand_index(ARCH)
    specs = [("all", None, None, None), *[(c, None, None, None) for c in ["US", "CA", "GB", "EU"] + sorted(EU_NAMES)]]
    specs += [("all", c, None, None) for c in CATSLUG]
    specs += [(code, c, None, None) for code in REGION_CODES for c in CATSLUG if len(select(code, c)) >= MIN_COUNTRY_CAT]
    specs += [("all", None, t, None) for t in TOPICS]
    for y in YEARS:  # year archive pages, only where there is enough to show
        specs.append(("all", None, None, y))
        specs += [(c, None, None, y) for c in ["US", "CA", "GB", "EU"] + sorted(EU_NAMES)
                  if len(select(c, None, None, y)) >= (1 if c in REGION_CODES else MIN_COUNTRY_CAT)]
        specs += [("all", c, None, y) for c in CATSLUG if len(select("all", c, None, y)) >= MIN_COUNTRY_CAT]
        specs += [(code, c, None, y) for code in REGION_CODES for c in CATSLUG
                  if len(select(code, c, None, y)) >= MIN_COUNTRY_CAT]
        specs += [("all", None, t, y) for t in TOPICS if len(select("all", None, t, y)) >= MIN_COUNTRY_CAT]
    BUILT.update(page_path(*s) for s in specs)
    nav_pages = sorted(p for p in BUILT if p != "/")
    browse = browse_html(nav_pages)
    lastmod = data["updated"][:10]
    page_urls = []
    for spec in specs:
        path = page_path(*spec)
        write(path, page(*spec, pages=nav_pages, browse=browse))
        y = spec[3]
        page_urls.append((SITE + path, lastmod if not y or y == YEARS[0] else f"{y}-12-31"))

    rows, brands = ARCH, BRANDS
    by_cc = defaultdict(list)
    for r in rows: by_cc[(r["category"], r["country"])].append(r)
    footer = footer_html(browse)
    for r in rows:
        write(f"/recall/{r['slug']}/", recall_page(r, brands, by_cc, footer))
    for k, (name, rs) in brands.items():
        write(f"/brand/{k}/", brand_page(k, name, rs, footer))
    write("/brand/", brands_index_page(brands, footer))

    maps = [sitemap("sitemap-pages.xml", page_urls + [(f"{SITE}/brand/", lastmod)])]
    maps.append(sitemap("sitemap-brands.xml", [(f"{SITE}/brand/{k}/", rs[0]["date"]) for k, (n, rs) in brands.items()]))
    for year in sorted({r["date"][:4] for r in rows}):
        maps.append(sitemap(f"sitemap-recalls-{year}.xml",
                            [(f"{SITE}/recall/{r['slug']}/", r["date"]) for r in rows if r["date"][:4] == year]))
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <sitemap><loc>{SITE}/{m}</loc><lastmod>{lastmod}</lastmod></sitemap>\n" for m in maps)
        + "</sitemapindex>\n")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    (OUT / f"{INDEXNOW_KEY}.txt").write_text(INDEXNOW_KEY)
    (OUT / "assets").mkdir(exist_ok=True)
    (OUT / "assets" / "site.css").write_text(CSS)
    for f in STATIC:
        if (ROOT / f).exists(): shutil.copy(ROOT / f, OUT / f)
    (OUT / "data").mkdir(exist_ok=True)
    (OUT / "data" / "recalls.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    (OUT / "data" / "years").mkdir(exist_ok=True)
    for y in YEARS:  # loaded by the Period filter
        yr = [{k: r.get(k, "") for k in KEEP if r.get(k) or k in ("hazard", "brand", "severity", "product")}
              for r in rows if r["date"][:4] == y]
        (OUT / "data" / "years" / f"{y}.json").write_text(
            json.dumps({"year": y, "count": len(yr), "recalls": yr}, ensure_ascii=False, separators=(",", ":")))
    write("/disclaimer/", disclaimer_page(footer))
    page_urls.append((f"{SITE}/disclaimer/", lastmod))
    (OUT / "404.html").write_text(
        head_html("Page not found | Recall Atlas", "This page does not exist.", SITE + "/")
        + f'<div class="wrap"><header class="top slim">{BRAND_A}</header><article class="recall"><h1>Page not found</h1>'
          '<p class="lede">That page does not exist or has moved. <a href="/">Search all recalls</a>.</p></article></div>'
        + footer + CONSENT + "</body>\n</html>\n")
    print(f"built {len(page_urls)} list pages, {len(rows)} recall pages, {len(brands)} brand pages")

    if "--indexnow" in sys.argv:
        today = dt.date.today().isoformat()
        indexnow([f"{SITE}/recall/{r['slug']}/" for r in rows if r.get("first_seen") == today])


if __name__ == "__main__":
    main()
