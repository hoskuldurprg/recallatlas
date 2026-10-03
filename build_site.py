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
TOPLINE = re.search(r'<div class="topline">.*?</div>', tpl, re.S).group(0)  # logo + light/dark toggle

NAMES = {"US": "United States", "CA": "Canada", "GB": "United Kingdom", "AU": "Australia", "NZ": "New Zealand",
         "EU": "the EU & EEA", **EU_NAMES}
COVERAGE = "the US, Canada, the UK, Europe, Australia and New Zealand"
CATS = {"food": "Food & drink", "kids": "Toys & kids", "electrical": "Electrical", "home": "Home & garden",
        "sports": "Sports & outdoor", "tools": "Tools & DIY", "vehicles": "Vehicles", "medical": "Drugs & medical",
        "cosmetics": "Cosmetics & chemicals", "apparel": "Clothing & jewellery", "other": "Other"}
SOURCES_BY_REGION = {
    "US": "the CPSC, FDA, NHTSA and USDA", "CA": "Health Canada, the CFIA and Transport Canada",
    "GB": "the Office for Product Safety and Standards and the Food Standards Agency",
    "AU": "the ACCC and Food Standards Australia New Zealand",
    "NZ": "Product Safety New Zealand (MBIE) and New Zealand Food Safety (MPI)",
    "EU": "the EU Safety Gate and RASFF food alerts"}
AGENCY = {"CPSC": "the US Consumer Product Safety Commission", "FDA": "the US Food and Drug Administration",
          "NHTSA": "the US National Highway Traffic Safety Administration",
          "USDA FSIS": "the USDA Food Safety and Inspection Service",
          "UK OPSS": "the UK Office for Product Safety and Standards", "UK FSA": "the UK Food Standards Agency",
          "Canada": "the Government of Canada", "EU Safety Gate": "the European Commission's Safety Gate",
          "EU RASFF": "the EU Rapid Alert System for Food and Feed",
          "AU ACCC": "the Australian Competition and Consumer Commission (ACCC)",
          "AU FSANZ": "Food Standards Australia New Zealand",
          "NZ Product Safety": "Product Safety New Zealand (MBIE)", "NZ Food Safety": "New Zealand Food Safety (MPI)"}
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
REGION_CODES = ["US", "CA", "GB", "AU", "NZ", "EU"]
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
                   for c in ["US", "CA", "GB", "AU", "NZ", "EU", "DE", "FR", "IT", "ES", "NL", "SE", "PL", "IE"])
    yrs = "".join(f'<li><a href="/recalls/{y}/">{y}</a></li>' for y in YEARS)
    return (f'<div class="browse"><div><h4>By country</h4><ul>{ctry}</ul></div>'
            f'<div><h4>By product type</h4><ul>{cats}</ul></div>'
            f'<div><h4>Common searches</h4><ul>{tops}</ul></div>'
            f'<div><h4>By year</h4><ul>{yrs}<li><a href="/weekly/">Weekly roundups</a></li><li><a href="/brand/">All brands</a></li></ul></div></div>')


def country_label(c):
    return "EU & EEA" if c == "EU" else NAMES.get(c, c)


def head_html(title, desc, url, kind="website", crumbs=None, image=None, extra_ld=None, feeds=()):
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
{"".join(f'<link rel="alternate" type="application/rss+xml" title="{esc(t)}" href="{SITE}{p}">' + chr(10) for p, t in feeds)}{ld_html}{head_tpl}</head>
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
    out = (f'<section class="ystats" id="ystats"><div><h4>Recalls in {year}</h4><div class="big">{len(rows):,}</div>'
           f'<p class="note">{esc((lambda t: t[:1].upper() + t[1:])(year_note(year).strip(" ()")))}</p></div>'
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
        desc = (f"{n} current {topic[1].lower()} recalls and safety alerts from {COVERAGE}, "
                "from official government sources. Updated every 6 hours.")
        h1 = what
        lede = (f"The latest official {topic[1].lower()} recalls from {COVERAGE}, "
                "updated every 6 hours. Pick your country to narrow the list.")
    elif cat:
        what = f"{CATS[cat]} recalls"
        title = f"{what}{where} | Recall Atlas"
        src = SOURCES_BY_REGION[region] if code != "all" else "government agencies in " + COVERAGE
        desc = f"{n} current {CATS[cat].lower()} recalls{where}, from {src}. Updated every 6 hours."
        h1 = what + where
        lede = f"Official {CATS[cat].lower()} recalls{where} from {src}, updated every 6 hours."
    elif code == "all":
        title = "Recall Atlas: product, food and vehicle recalls in one list"
        desc = (f"{data['count']} official product, food, drug and vehicle recalls from {COVERAGE}, "
                "searchable by country. Updated every 6 hours.")
        h1 = "Is anything you own recalled?"
        lede = ("Official product, food, drug and vehicle recalls from the US, Canada, the UK, 30 European countries, "
                "Australia and New Zealand, "
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
        src = SOURCES_BY_REGION[region] if code != "all" else "government agencies in " + COVERAGE
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
    feeds = page_feeds(code, cat)
    head = head_html(title, desc, url, "website", crumbs if len(crumbs) > 1 else None, feeds=feeds)
    topic_js = json.dumps({"name": topic[1], "words": topic[2]}) if topic else "null"
    body = (body_tpl.replace("{{H1}}", esc(h1)).replace("{{H2}}", esc(h2)).replace("{{LEDE}}", esc(lede))
            .replace("{{PRERENDER}}", render_rows(rows[:PRERENDER]))
            .replace("{{PRESET}}", "" if code == "all" else code)
            .replace("{{PCAT}}", cat or "").replace("{{TOPIC}}", topic_js)
            .replace("{{PYEAR}}", year or "").replace("{{YEARS}}", json.dumps([int(y) for y in YEARS]))
            .replace("{{STATS}}", stats_html(rows, code, cat, year) if year else '<section class="ystats" id="ystats" hidden></section>')
            .replace("{{PAGES}}", json.dumps(sorted(pages)))
            .replace("{{BROWSE}}", browse)
            .replace("{{WEEKLY}}", f'<a class="rss" href="/weekly/{LATEST_WEEK}/">This week\'s roundup</a>' if LATEST_WEEK and code == "all" and not cat and not topic and not year else "")
            .replace("{{FEED}}", f'<a class="rss" href="{feeds[0][0]}" title="{esc(feeds[0][1])}">RSS feed</a>')
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
<header class="top slim">{TOPLINE}</header>
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
            'them. <a href="/feeds/">RSS feeds</a> · <a href="/privacy/">Privacy and cookies</a> · <button class="linkbtn" id="privacyBtn" type="button">Change cookie settings</button></p></div></footer>\n')


def brand_page(k, name, rs, footer):
    years = f"{rs[-1]['date'][:4]}" + (f"–{rs[0]['date'][:4]}" if rs[-1]['date'][:4] != rs[0]['date'][:4] else "")
    srcs = sorted({r["source"] for r in rs})
    title = f"{name} recalls ({len(rs)}) | Recall Atlas"
    desc = (f"All {len(rs)} official {name} recalls and safety alerts ({years}) from "
            f"{', '.join(srcs[:4])}. Updated every 6 hours.")
    crumbs = [("Recall Atlas", "/"), ("Brands", "/brand/"), (name, f"/brand/{k}/")]
    nav = " › ".join(f'<a href="{p}">{esc(n)}</a>' for n, p in crumbs)
    body = f"""<div class="wrap">
<header class="top slim">{TOPLINE}</header>
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
<header class="top slim">{TOPLINE}</header>
<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Recall Atlas</a> › <a href="/brand/">Brands</a></nav>
<article class="recall"><h1>Recalls by brand</h1>
<p class="lede">{len(items)} brands with more than one official recall. Pick a brand to see every recall in one list.</p>
<ul class="brands">{lis}</ul></article></div>
{footer}{CONSENT}"""
    return head_html("Product recalls by brand A–Z | Recall Atlas",
                     f"Recall history for {len(items)} brands, from official sources in {COVERAGE}.",
                     f"{SITE}/brand/", "website", crumbs) + body + "</body>\n</html>\n"


DISCLAIMER_FULL = [
    ("What this site is", "Recall Atlas is an independent website that gathers product, food, drug and vehicle recalls "
     "published by government agencies in the United States, Canada, the United Kingdom, the European Union, Australia and "
     "New Zealand, and shows "
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
<header class="top slim">{TOPLINE}</header>
<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Recall Atlas</a> › <a href="/disclaimer/">Disclaimer</a></nav>
<article class="recall prose"><h1>Disclaimer</h1>{secs}</article></div>
{footer}{CONSENT}"""
    return head_html("Disclaimer | Recall Atlas", "How Recall Atlas collects recall information and the limits of that information.",
                     f"{SITE}/disclaimer/", "website", crumbs) + body + "</body>\n</html>\n"


# ---------- fonts ----------
# Self-hosted fonts live in assets/fonts/. Any that are missing from the repo are downloaded from the npm registry
# (pinned Fontsource packages, checked against these hashes); if that fails the site falls back to system fonts.
FONT_PKGS = {"archivo": "@fontsource-variable/archivo/-/archivo-5.3.0.tgz",
             "public-sans": "@fontsource-variable/public-sans/-/public-sans-5.3.0.tgz",
             "ibm-plex-mono": "@fontsource/ibm-plex-mono/-/ibm-plex-mono-5.3.0.tgz"}
FONT_FILES = {
    "archivo-latin-ext-wdth-normal.woff2": "5717f37059660ca5", "archivo-latin-wdth-normal.woff2": "e3a28eade21a900c",
    "ibm-plex-mono-latin-400-normal.woff2": "08949f728dc52d52", "ibm-plex-mono-latin-500-normal.woff2": "01d285447409c8a5",
    "ibm-plex-mono-latin-ext-400-normal.woff2": "6bc0f226a5b7884a", "ibm-plex-mono-latin-ext-500-normal.woff2": "6bb06407c97584b0",
    "public-sans-latin-ext-wght-italic.woff2": "a071e35bbfc9c627", "public-sans-latin-ext-wght-normal.woff2": "3a00a32f0242b723",
    "public-sans-latin-wght-italic.woff2": "16dc93252adb7878", "public-sans-latin-wght-normal.woff2": "5ed4d31c988e73b2"}


def ensure_fonts():
    import io, tarfile
    d = ROOT / "assets" / "fonts"
    d.mkdir(parents=True, exist_ok=True)
    missing = [f for f in FONT_FILES if not (d / f).exists()]
    if not missing and (d / "LICENSE.txt").exists(): return
    licenses = []
    for pkg, path in FONT_PKGS.items():
        need = [f for f in missing if f.startswith(pkg)]
        try:
            with urllib.request.urlopen("https://registry.npmjs.org/" + path, timeout=60) as res:
                tar = tarfile.open(fileobj=io.BytesIO(res.read()))
            licenses.append(tar.extractfile("package/LICENSE").read().decode())
            for f in need:
                data_ = tar.extractfile("package/files/" + f).read()
                if hashlib.sha256(data_).hexdigest()[:16] != FONT_FILES[f]: raise ValueError(f"hash mismatch {f}")
                (d / f).write_bytes(data_)
        except Exception as e:
            print(f"fonts: could not fetch {pkg} ({e}); pages fall back to system fonts", file=sys.stderr)
    if licenses and not (d / "LICENSE.txt").exists():
        (d / "LICENSE.txt").write_text("Self-hosted web fonts from Fontsource, SIL Open Font License 1.1.\n\n" + "\n\n".join(licenses))
    print(f"fonts: fetched {len([f for f in missing if (d / f).exists()])} of {len(missing)} missing files")


# ---------- RSS feeds ----------
FEED_ITEMS = 50
LATEST_WEEK = None  # newest weekly roundup, linked from the home page
FEEDS = {"/feed.xml"} | {f"/recalls/{v}/feed.xml" for v in CATSLUG.values()} | {f"/{slug(c)}/feed.xml" for c in NAMES
                                                                              if any(matches(r, c) for r in ARCH)}


def feed_path(code="all", cat=None):
    if cat: return f"/recalls/{CATSLUG[cat]}/feed.xml"
    return "/feed.xml" if code == "all" else f"/{slug(code)}/feed.xml"


def feed_title(code="all", cat=None):
    if cat: return f"Recall Atlas: {CATS[cat].lower()} recalls"
    if code == "all": return "Recall Atlas: all recalls"
    return f"Recall Atlas: recalls in {'the ' if code in ('US', 'GB', 'NL') else ''}{country_label(code)}"


def page_feeds(code="all", cat=None):
    """Feeds offered on a list page: the most specific first (country, then product type), else the all-recalls feed."""
    out = []
    if code != "all" and feed_path(code) in FEEDS: out.append((feed_path(code), feed_title(code)))
    if cat: out.append((feed_path("all", cat), feed_title("all", cat)))
    return out or [(feed_path(), feed_title())]


def seen_date(r):
    fs = r.get("first_seen") or ""
    return fs if re.match(r"\d{4}-\d\d-\d\d$", fs) else r["date"]


def rfc822(day):
    import email.utils
    return email.utils.format_datetime(dt.datetime.fromisoformat(day + "T12:00:00+00:00"))


def feed_xml(code, cat, rows, updated):
    rows = sorted(rows, key=lambda r: (seen_date(r), r["date"], r["id"]), reverse=True)[:FEED_ITEMS]
    page = SITE + page_path(code, cat)
    where = "" if code == "all" else f" affecting {('the ' if code in ('US', 'GB', 'NL') else '')}{NAMES.get(code, code)}"
    what = f"{CATS[cat].lower()} recalls" if cat else "product, food, drug and vehicle recalls"
    items = []
    for r in rows:
        u = f"{SITE}/recall/{r['slug']}/"
        body = ((f"<p>{esc(r['hazard'])}</p>" if r.get("hazard") else "")
                + f"<p>{esc(AGENCY.get(r.get('feed'), r['source']))[:1].upper()}{esc(AGENCY.get(r.get('feed'), r['source']))[1:]} · {esc(r.get('countryName') or r['country'])} · {esc(r['date'])}</p>"
                + f'<p><a href="{esc(r["url"])}">Official notice</a> · <a href="{u}">On Recall Atlas</a></p>')
        items.append(f"<item><title>{esc(r['title'])}</title><link>{u}</link><guid isPermaLink=\"true\">{u}</guid>"
                     f"<pubDate>{rfc822(seen_date(r))}</pubDate><category>{esc(CATS.get(r['category'], 'Other'))}</category>"
                     f"<description>{esc(body)}</description></item>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>\n'
            f"<title>{esc(feed_title(code, cat))}</title><link>{page}</link>\n"
            f"<description>{esc(f'Official {what}{where}, collected from government sources by Recall Atlas every 6 hours.')}</description>\n"
            f'<language>en</language><ttl>360</ttl><lastBuildDate>{email_date(updated)}</lastBuildDate>\n'
            f'<atom:link href="{SITE}{feed_path(code, cat)}" rel="self" type="application/rss+xml"/>\n'
            f"<image><url>{SITE}/apple-touch-icon.png</url><title>{esc(feed_title(code, cat))}</title><link>{page}</link></image>\n"
            + "\n".join(items) + "\n</channel>\n</rss>\n")


def email_date(updated):
    import email.utils
    return email.utils.format_datetime(dt.datetime.strptime(updated, "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.timezone.utc))


def feeds_page(feeds, footer):
    def ul(fs): return "<ul class=\"feeds\">" + "".join(f'<li><a href="{p}">{esc((lambda x: x[:1].upper() + x[1:])(t.replace("Recall Atlas: ", "")))}</a> <code>{SITE}{p}</code></li>' for p, t in fs) + "</ul>"
    groups = [("Everything", [f for f in feeds if f[0] == "/feed.xml"]),
              ("By country", [f for f in feeds if f[0] != "/feed.xml" and not f[0].startswith("/recalls/")]),
              ("By product type", [f for f in feeds if f[0].startswith("/recalls/")])]
    crumbs = [("Recall Atlas", "/"), ("RSS feeds", "/feeds/")]
    body = f"""<div class="wrap">
<header class="top slim">{TOPLINE}</header>
<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Recall Atlas</a> › <a href="/feeds/">RSS feeds</a></nav>
<article class="recall prose"><h1>RSS feeds</h1>
<p class="lede">Follow new recalls in a feed reader, or use a feed to post recalls to your own site, newsletter or chat. Each feed has the {FEED_ITEMS} newest recalls and updates every 6 hours. Copy a feed address into your reader.</p>
{"".join(f"<h2>{h}</h2>{ul(fs)}" for h, fs in groups)}
<p class="note">Feeds are free to use. Please link to the official notice, and keep in mind the <a href="/disclaimer/">disclaimer</a>.</p>
</article></div>
{footer}{CONSENT}"""
    return head_html("RSS feeds | Recall Atlas", "Free RSS feeds of official recalls: all recalls, by country and by product type. Updated every 6 hours.",
                     f"{SITE}/feeds/", "website", crumbs, feeds=[(p, t) for p, t in feeds if p == "/feed.xml"]) + body + "</body>\n</html>\n"


# ---------- weekly roundups (/weekly/YYYY-wNN/) ----------
# One page per ISO week (Monday-Sunday) by the date the agency published the recall. The current week is "so far".
REGION_ORDER = [("US", "United States"), ("CA", "Canada"), ("GB", "United Kingdom"), ("AU", "Australia"),
                ("NZ", "New Zealand"), ("EU", "EU & EEA")]


def week_key(day):
    y, w, _ = dt.date.fromisoformat(day).isocalendar()
    return f"{y}-w{w:02d}"


def week_range(key):
    y, w = int(key[:4]), int(key[6:])
    mon = dt.date.fromisocalendar(y, w, 1)
    return mon, mon + dt.timedelta(days=6)


def fmt_day(d, year=True):
    return f"{d.day} {MON[d.month - 1]}" + (f" {d.year}" if year else "")


def week_label(key):
    mon, sun = week_range(key)
    return f"{fmt_day(mon, mon.year != sun.year)} – {fmt_day(sun)}"


def region_of(r):
    return "EU" if r.get("region") == "EU" else r["country"]


def week_groups(rows, today):
    g = defaultdict(list)
    for r in rows:
        if r["date"] >= FIRST_DAY and r["date"] <= today: g[week_key(r["date"])].append(r)
    first = week_key(FIRST_DAY)
    return {k: v for k, v in sorted(g.items()) if k >= first and len(v) >= 20}


def week_topics(rows):
    out = []
    for t in TOPICS:
        rx = topic_rx(t[2])
        n = sum(1 for r in rows if rx.search(f'{r["title"]} {r["hazard"]} {r.get("product", "")}'))
        if n: out.append((t, n))
    return sorted(out, key=lambda x: -x[1])


def week_summary(key, rows, prev, current):
    n = len(rows)
    s = f"{n:,} official recalls and safety alerts {'so far in' if current else 'were published in'} the week of {week_label(key)}"
    if prev and not current:
        ch = round((n - len(prev)) / len(prev) * 100)
        s += f", {'up' if ch > 0 else 'down'} {abs(ch)}% on the week before ({len(prev):,})" if ch else ", the same as the week before"
    cats = Counter(r["category"] for r in rows).most_common(2)
    s += ". Most were " + " and ".join(f"{CATS.get(c, 'Other').lower()} ({k})" for c, k in cats)
    tops = [f"{t[1].lower()} ({k})" for t, k in week_topics(rows)[:3]]
    if tops: s += "; common issues included " + ", ".join(tops)
    hi = sum(1 for r in rows if sev_class((r.get("severity") or "") + " " + (r.get("hazard") or "")) == "high")
    return s + f". {hi} {'was' if hi == 1 else 'were'} flagged as serious." if hi else s + "."


def serious(rows, n=10):
    return [r for r in rows if sev_class((r.get("severity") or "") + " " + (r.get("hazard") or "")) == "high"][:n]


def week_page(key, rows, prev_key, next_key, prev_rows, current, footer):
    rows = sorted(rows, key=lambda r: (r["date"], r["id"]), reverse=True)
    y, w = key[:4], int(key[6:])
    label = week_label(key)
    h1 = f"Recall roundup: {label}" + (" (so far)" if current else "")
    summ = week_summary(key, rows, prev_rows, current)
    reg = Counter(region_of(r) for r in rows)
    eu = Counter(r["country"] for r in rows if region_of(r) == "EU" and r["country"] in EU_NAMES).most_common(5)
    lis = lambda pairs: "<ol>" + "".join(f"<li>{a}<span>{n}</span></li>" for a, n in pairs) + "</ol>"
    blocks = [f'<div><h4>Recalls this week</h4><div class="big">{len(rows):,}</div><p class="note">{"So far" if current else esc(label)}</p></div>',
              "<div><h4>By country</h4>" + lis([(f'<a href="{page_path(c)}">{esc(n)}</a>', reg[c]) for c, n in REGION_ORDER if reg[c]]
                                             + [(f'<a href="{page_path(c)}">{esc(EU_NAMES[c])}</a>', k) for c, k in eu]) + "</div>",
              "<div><h4>By product type</h4>" + lis([(f'<a href="{page_path("all", c)}">{CATS[c]}</a>' if c in CATSLUG else CATS.get(c, "Other"), k)
                                                  for c, k in Counter(r["category"] for r in rows).most_common(6)]) + "</div>"]
    bc = [(k, n) for k, n in Counter(r["_brand"] for r in rows if r.get("_brand")).most_common(6) if n > 1]
    if bc: blocks.append("<div><h4>Most recalled brands</h4>" + lis([(f'<a href="/brand/{k}/">{esc(BRANDS[k][0])}</a>', n) for k, n in bc]) + "</div>")
    tp = week_topics(rows)[:6]
    if tp: blocks.append("<div><h4>Common searches</h4>" + lis([(f'<a href="/recalls/{t[0]}/">{esc(t[1])}</a>', n) for t, n in tp]) + "</div>")
    ser = serious(rows)
    parts = [f'<section class="ystats wk">{"".join(blocks)}</section>']
    if ser: parts.append(f'<h2>Most serious</h2><p class="note">Recalls the agency classed as serious, or with a risk of death, fire, electric shock, drowning or strangulation.</p><ol class="list">{render_rows(ser)}</ol>')
    for c, n in REGION_ORDER:
        rs = [r for r in rows if region_of(r) == c]
        if rs: parts.append(f'<h2>{esc(n)} <span class="cnt">{len(rs)}</span></h2><ol class="list">{render_rows(rs)}</ol>')
    nav = ('<nav class="wknav">' + (f'<a href="/weekly/{prev_key}/">← {esc(week_label(prev_key))}</a>' if prev_key else "<span></span>")
           + '<a href="/weekly/">All weeks</a>' + (f'<a href="/weekly/{next_key}/">{esc(week_label(next_key))} →</a>' if next_key else "<span></span>") + "</nav>")
    crumbs = [("Recall Atlas", "/"), ("Weekly roundups", "/weekly/"), (f"Week {w}, {y}", f"/weekly/{key}/")]
    body = f"""<div class="wrap">
<header class="top slim">{TOPLINE}</header>
<nav class="crumbs" aria-label="Breadcrumb">{" › ".join(f'<a href="{p}">{esc(n)}</a>' for n, p in crumbs)}</nav>
<article class="recall weekly">
<h1>{esc(h1)}</h1>
<p class="lede">{esc(summ)}</p>
{"".join(parts)}
{nav}
<p class="note">Collected automatically from official sources. Check each official notice for exact models, batch codes and remedies. <a href="/disclaimer/">Disclaimer</a></p>
</article></div>
{footer}{CONSENT}"""
    title = f"Recall roundup, week {w} {y} ({label}) | Recall Atlas"
    desc = summ[:155].rsplit(" ", 1)[0] + "…" if len(summ) > 158 else summ
    return head_html(title, desc, f"{SITE}/weekly/{key}/", "article", crumbs,
                     feeds=[("/weekly/feed.xml", "Recall Atlas: weekly roundups")]) + body + "</body>\n</html>\n"


def weekly_index(weeks, current_key, footer):
    by_year = defaultdict(list)
    for k, rs in weeks.items(): by_year[k[:4]].append((k, len(rs)))
    secs = "".join(f"<h2>{y}</h2><ul class=\"weeks\">" + "".join(
        f'<li><a href="/weekly/{k}/">Week {int(k[6:])}</a><span>{esc(week_label(k))}</span><span>{n:,} recalls{" so far" if k == current_key else ""}</span></li>'
        for k, n in sorted(items, reverse=True)) + "</ul>" for y, items in sorted(by_year.items(), reverse=True))
    crumbs = [("Recall Atlas", "/"), ("Weekly roundups", "/weekly/")]
    body = f"""<div class="wrap">
<header class="top slim">{TOPLINE}</header>
<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Recall Atlas</a> › <a href="/weekly/">Weekly roundups</a></nav>
<article class="recall"><h1>Weekly recall roundups</h1>
<p class="lede">Every week's official recalls from {COVERAGE} on one page: the most serious ones, counts by country and product type, and the brands recalled most. Weeks run Monday to Sunday. Follow new roundups with the <a href="/weekly/feed.xml">weekly RSS feed</a>.</p>
{secs}</article></div>
{footer}{CONSENT}"""
    return head_html("Weekly recall roundups | Recall Atlas",
                     f"Every week's official product, food and vehicle recalls from {COVERAGE}, summarised on one page.",
                     f"{SITE}/weekly/", "website", crumbs, feeds=[("/weekly/feed.xml", "Recall Atlas: weekly roundups")]) + body + "</body>\n</html>\n"


def weekly_feed(weeks, done, updated):
    items = []
    for k in done[-30:][::-1]:
        rs = weeks[k]; u = f"{SITE}/weekly/{k}/"
        prev = weeks.get(done[done.index(k) - 1]) if done.index(k) else None
        ser = serious(sorted(rs, key=lambda r: (r["date"], r["id"]), reverse=True), 5)
        body = f"<p>{esc(week_summary(k, rs, prev, False))}</p>" + (
            "<p>Most serious:</p><ul>" + "".join(f'<li><a href="{SITE}/recall/{r["slug"]}/">{esc(r["title"])}</a></li>' for r in ser) + "</ul>" if ser else "")
        sun = week_range(k)[1] + dt.timedelta(days=1)
        items.append(f"<item><title>{esc(f'Recall roundup: {week_label(k)}')}</title><link>{u}</link><guid isPermaLink=\"true\">{u}</guid>"
                     f"<pubDate>{rfc822(sun.isoformat())}</pubDate><description>{esc(body)}</description></item>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>\n'
            f"<title>Recall Atlas: weekly roundups</title><link>{SITE}/weekly/</link>\n"
            f"<description>A weekly summary of official recalls from {COVERAGE}.</description>\n"
            f'<language>en</language><ttl>360</ttl><lastBuildDate>{email_date(updated)}</lastBuildDate>\n'
            f'<atom:link href="{SITE}/weekly/feed.xml" rel="self" type="application/rss+xml"/>\n'
            + "\n".join(items) + "\n</channel>\n</rss>\n")


# ---------- privacy and cookies ----------
OPERATOR = "Frostinn ehf."
PRIVACY_UPDATED = "2026-10-01"
# Contact form on /privacy/ (no email address is published). The form lives at Tally and is linked, not embedded,
# so nothing loads from Tally until a visitor opens it. Paste the form's share link (https://tally.so/r/xxxxxx) into "url".
CONTACT_FORM = {"provider": "Tally (Tally BV, Belgium)", "url": "https://tally.so/r/rjzg1N", "privacy_url": "https://tally.so/privacy"}
GA_COOKIES = "<code>_ga</code> and <code>_ga_VYHRQZSXSN</code>"


def privacy_sections():
    f = CONTACT_FORM
    form_proc = (f'The contact form is run by {esc(f["provider"])}, which processes your message on our behalf '
                 f'(<a href="{esc(f["privacy_url"])}" rel="noopener" target="_blank">Tally\'s privacy policy</a>). '
                 "Nothing is loaded from Tally until you open the form.")
    return [
        ("Who runs Recall Atlas",
         f"<p>Recall Atlas is run by {OPERATOR}, a company registered in Iceland, which is the data controller for this "
         "website. You can reach us with the contact form at the bottom of this page.</p>" if f["url"] else
         "website.</p>"),
        ("The short version",
         "<p>You can use Recall Atlas without an account and without being tracked. We do not show ads, sell data or build "
         "profiles. Visitor statistics are only collected if you click <b>Accept</b> in the cookie banner, and you can "
         "change that at any time.</p>"),
        ("Visitor statistics (Google Analytics)",
         "<p>If you accept, we load Google Analytics 4 to count visits: pages viewed, the site that referred you, your "
         "approximate location (country and city, worked out from your IP address), device and browser type, and language. "
         "Google Analytics 4 does not store IP addresses. Google sets two cookies, "
         f"{GA_COOKIES}, which keep a random ID for up to two years so repeat visits can be counted. We use the reports "
         "only to see which countries, recalls and pages people use, so we can improve the site.</p>"
         "<p>The legal basis is your consent (GDPR Article 6(1)(a)). Google Ireland Limited processes the data on our "
         "behalf, and it may be transferred to Google LLC in the United States, which is certified under the EU–US Data "
         "Privacy Framework. Google keeps the data for no more than 14 months. If you decline, or never answer the "
         "banner, Google Analytics is not loaded at all and no request is sent to Google. "
         '<a href="https://policies.google.com/privacy" rel="noopener" target="_blank">Google\'s privacy policy</a>.</p>'),
        ("What is stored in your browser",
         "<p>Without your consent we set no cookies. The site keeps two small settings in your browser's local storage. "
         "They never leave your device and we cannot read them:</p><ul>"
         "<li><code>ra-consent</code>: whether you accepted or declined visitor statistics, so we do not ask again</li>"
         "<li><code>ra-theme</code>: light or dark theme, only if you picked one that differs from your device setting</li>"
         f"</ul><p>If you accept statistics, Google Analytics adds the cookies {GA_COOKIES} described above. "
         "Clearing your browser's site data removes all of these.</p>"),
        ("Change or withdraw your consent",
         '<p>Use <button class="linkbtn" type="button" data-consent>Change cookie settings</button> (also at the bottom of '
         "every page) and choose <b>Decline</b>. Google Analytics then stops loading. Withdrawing consent does not affect "
         "statistics already collected.</p>"),
        ("Hosting and other services",
         "<p>The site is hosted on GitHub Pages (GitHub, Inc., USA). Like any web server, GitHub receives your IP address "
         "when you load a page and logs it for security purposes; we do not receive these logs. "
         '<a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement" rel="noopener" target="_blank">GitHub\'s privacy statement</a>.</p>'
         "<p>Fonts are served from recallatlas.org itself, not from Google. Some recall pages show a product photo that "
         "is loaded directly from the government agency that published the recall, so that agency's server sees your IP "
         "address. Links to official notices take you to the agency's own website, where its privacy policy applies.</p>"
         + (f"<p>{form_proc}</p>" if f["url"] else "")),
        ("If you contact us",
         "<p>We use your name, email address and message only to reply to you, and delete them within 12 months after "
         "the conversation ends unless we need them for a legal claim. The legal basis is our legitimate interest in "
         "answering messages (GDPR Article 6(1)(f)).</p>"),
        ("Your rights",
         "<p>Under the GDPR and the UK GDPR you can ask for access to, correction or deletion of personal data we hold "
         "about you, ask us to restrict or stop processing it, and receive it in a portable format. Where processing is "
         "based on consent you can withdraw it at any time. Because we hold almost nothing about visitors, most "
         "statistics data can only be found through Google. You can also complain to a data protection authority: in "
         'Iceland that is <a href="https://www.personuvernd.is/" rel="noopener" target="_blank">Persónuvernd</a>, '
         "or the authority where you live or work.</p>"),
        ("Children",
         "<p>Recall Atlas is a general information site and is not aimed at children. We do not knowingly collect data "
         "about children.</p>"),
        ("Changes",
         f"<p>We will update this page if anything changes, and change the date below. Last updated {PRIVACY_UPDATED}.</p>"),
    ]


def contact_form_html():
    f = CONTACT_FORM
    if not f["url"]:
        return ""
    return ('<h2 id="contact">Contact us</h2><p>Questions about this page, your data or a recall listed on Recall Atlas: '
            'use our contact form. It opens on tally.so.</p>'
            f'<a class="cta" href="{esc(f["url"])}" rel="noopener" target="_blank">Open the contact form →</a>')


def privacy_page(footer):
    secs = "".join(f"<h2>{h}</h2>{b}" for h, b in privacy_sections())
    crumbs = [("Recall Atlas", "/"), ("Privacy and cookies", "/privacy/")]
    body = f"""<div class="wrap">
<header class="top slim">{TOPLINE}</header>
<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Recall Atlas</a> › <a href="/privacy/">Privacy and cookies</a></nav>
<article class="recall prose"><h1>Privacy and cookies</h1>{secs}{contact_form_html()}</article></div>
{footer}{CONSENT}"""
    return head_html("Privacy and cookies | Recall Atlas",
                     "What Recall Atlas collects (nothing unless you accept statistics), the cookies and storage it uses, and your rights.",
                     f"{SITE}/privacy/", "website", crumbs) + body + "</body>\n</html>\n"


# ---------- year files (/data/years/<year>.json) ----------
# Format v2: one array per recall instead of an object, with everything the list view can rebuild left out.
#   {"v":2, "year":"2025", "count":N, "src":[sources], "cat":[categories], "u":[url prefixes], "r":[rows]}
#   "h": hazard texts used more than once; a row's hazard is either the text or an index into "h"
#   row = [MMDD, country, src index, cat index, title, hazard, brand, severity, units,
#          url prefix index (-1 = none), url rest (0 = slugified title), slug (6-char id = slugified title + id),
#          product ("" when its words are already in title/hazard), countries, brand index into "b" ([slug, name])]
#   Trailing empty values are dropped. region and countryName are derived from country.
YCATS = list(CATS)
_norm = lambda s: re.sub(r"\s+", " ", (s or "").lower()).strip()


def year_file(y, rs):
    pre = Counter(r["url"][:r["url"].rfind("/") + 1] for r in rs)
    prefixes = [p for p, n in pre.most_common() if n >= 20 and len(p) > 12]
    pidx = {p: i for i, p in enumerate(prefixes)}
    srcs = sorted({r["source"] for r in rs})
    sidx = {s: i for i, s in enumerate(srcs)}
    hz = [h for h, n in Counter(r.get("hazard") or "" for r in rs).most_common() if n > 1 and len(h) > 3]
    hidx = {h: i for i, h in enumerate(hz)}
    bt = sorted({r["_brand"] for r in rs if r.get("_brand")})
    bidx = {k: i for i, k in enumerate(bt)}
    out = []
    for r in rs:
        t = r["title"]
        ts = crawl.slugify(t)
        p = r["url"][:r["url"].rfind("/") + 1]
        pi = pidx.get(p, -1)
        rest = r["url"][len(p):] if pi >= 0 else r["url"]
        if pi >= 0 and rest == ts: rest = 0
        sl = r["slug"][len(ts) + 1:] if r.get("slug", "").startswith(ts + "-") and len(r["slug"]) == len(ts) + 7 else r.get("slug", "")
        prod = r.get("product") or ""
        if _norm(prod) in _norm(t + " " + (r.get("hazard") or "")): prod = ""
        row = [r["date"][5:7] + r["date"][8:10], r["country"], sidx[r["source"]],
               YCATS.index(r["category"]) if r["category"] in YCATS else YCATS.index("other"),
               t, hidx.get(r.get("hazard") or "", r.get("hazard") or ""), r.get("brand") or "", r.get("severity") or "", r.get("units") or "",
               pi, rest, sl, prod, r.get("countries") or "", bidx.get(r.get("_brand"), "")]
        while row and row[-1] in ("", None): row.pop()
        out.append(row)
    return {"v": 2, "year": y, "count": len(out), "src": srcs, "cat": YCATS, "u": prefixes, "h": hz, "b": [[k, BRANDS[k][0]] for k in bt], "r": out}


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
    specs = [("all", None, None, None), *[(c, None, None, None) for c in REGION_CODES + sorted(EU_NAMES)]]
    specs += [("all", c, None, None) for c in CATSLUG]
    specs += [(code, c, None, None) for code in REGION_CODES for c in CATSLUG if len(select(code, c)) >= MIN_COUNTRY_CAT]
    specs += [("all", None, t, None) for t in TOPICS]
    for y in YEARS:  # year archive pages, only where there is enough to show
        specs.append(("all", None, None, y))
        specs += [(c, None, None, y) for c in REGION_CODES + sorted(EU_NAMES)
                  if len(select(c, None, None, y)) >= (1 if c in REGION_CODES else MIN_COUNTRY_CAT)]
        specs += [("all", c, None, y) for c in CATSLUG if len(select("all", c, None, y)) >= MIN_COUNTRY_CAT]
        specs += [(code, c, None, y) for code in REGION_CODES for c in CATSLUG
                  if len(select(code, c, None, y)) >= MIN_COUNTRY_CAT]
        specs += [("all", None, t, y) for t in TOPICS if len(select("all", None, t, y)) >= MIN_COUNTRY_CAT]
    BUILT.update(page_path(*s) for s in specs)
    global LATEST_WEEK
    LATEST_WEEK = max(week_groups(ARCH, data["updated"][:10]), default=None)
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

    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    (OUT / f"{INDEXNOW_KEY}.txt").write_text(INDEXNOW_KEY)
    (OUT / "assets").mkdir(exist_ok=True)
    (OUT / "assets" / "site.css").write_text(CSS)
    ensure_fonts()
    shutil.copytree(ROOT / "assets" / "fonts", OUT / "assets" / "fonts")
    for f in STATIC:
        if (ROOT / f).exists(): shutil.copy(ROOT / f, OUT / f)
    (OUT / "data").mkdir(exist_ok=True)
    bkey = {r["id"]: r["_brand"] for r in rows if r.get("_brand")}  # brand page slug, used by the stats block
    out_data = dict(data, brands={}, recalls=[dict(r, bk=bkey[r["id"]]) if r["id"] in bkey else r for r in data["recalls"]])
    out_data["brands"] = {k: BRANDS[k][0] for k in {r["bk"] for r in out_data["recalls"] if r.get("bk")}}
    (OUT / "data" / "recalls.json").write_text(json.dumps(out_data, ensure_ascii=False, separators=(",", ":")))
    (OUT / "data" / "years").mkdir(exist_ok=True)
    for y in YEARS:  # loaded by the Period filter; compact format, decoded by decodeYear() in template.html
        (OUT / "data" / "years" / f"{y}.json").write_text(
            json.dumps(year_file(y, [r for r in rows if r["date"][:4] == y]), ensure_ascii=False, separators=(",", ":")))
    write("/disclaimer/", disclaimer_page(footer))
    page_urls.append((f"{SITE}/disclaimer/", lastmod))
    feeds = [("all", None)] + [(c, None) for c in REGION_CODES + sorted(EU_NAMES)
                               if any(matches(r, c) for r in rows)] + [("all", c) for c in CATSLUG]
    FEEDS.update(feed_path(c, k) for c, k in feeds)
    for code, cat in feeds:
        (OUT / feed_path(code, cat).lstrip("/")).parent.mkdir(parents=True, exist_ok=True)
        (OUT / feed_path(code, cat).lstrip("/")).write_text(
            feed_xml(code, cat, [r for r in rows if matches(r, code) and (not cat or r["category"] == cat)], data["updated"]))
    write("/feeds/", feeds_page([(feed_path(c, k), feed_title(c, k)) for c, k in feeds], footer))
    page_urls.append((f"{SITE}/feeds/", lastmod))
    weeks = week_groups(rows, data["updated"][:10])
    keys = list(weeks)
    current_key = week_key(data["updated"][:10])
    for i, k in enumerate(keys):
        write(f"/weekly/{k}/", week_page(k, weeks[k], keys[i - 1] if i else None, keys[i + 1] if i + 1 < len(keys) else None,
                                         weeks[keys[i - 1]] if i else None, k == current_key, footer))
    write("/weekly/", weekly_index(weeks, current_key, footer))
    done = [k for k in keys if k != current_key]
    (OUT / "weekly" / "feed.xml").write_text(weekly_feed(weeks, done, data["updated"]))
    weekly_urls = [(f"{SITE}/weekly/", lastmod)] + [
        (f"{SITE}/weekly/{k}/", min(lastmod, (week_range(k)[1] + dt.timedelta(days=1)).isoformat())) for k in keys]
    write("/privacy/", privacy_page(footer))
    page_urls.append((f"{SITE}/privacy/", PRIVACY_UPDATED))
    maps = [sitemap("sitemap-pages.xml", page_urls + [(f"{SITE}/brand/", lastmod)])]
    maps.append(sitemap("sitemap-brands.xml", [(f"{SITE}/brand/{k}/", rs[0]["date"]) for k, (n, rs) in brands.items()]))
    maps.append(sitemap("sitemap-weekly.xml", weekly_urls))
    for year in sorted({r["date"][:4] for r in rows}):
        maps.append(sitemap(f"sitemap-recalls-{year}.xml",
                            [(f"{SITE}/recall/{r['slug']}/", r["date"]) for r in rows if r["date"][:4] == year]))
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <sitemap><loc>{SITE}/{m}</loc><lastmod>{lastmod}</lastmod></sitemap>\n" for m in maps)
        + "</sitemapindex>\n")
    (OUT / "404.html").write_text(
        head_html("Page not found | Recall Atlas", "This page does not exist.", SITE + "/")
        + f'<div class="wrap"><header class="top slim">{TOPLINE}</header><article class="recall"><h1>Page not found</h1>'
          '<p class="lede">That page does not exist or has moved. <a href="/">Search all recalls</a>.</p></article></div>'
        + footer + CONSENT + "</body>\n</html>\n")
    print(f"built {len(specs)} list pages, {len(rows)} recall pages, {len(brands)} brand pages, {len(keys)} weekly roundups, {len(feeds) + 1} feeds")

    if "--indexnow" in sys.argv:
        today = dt.date.today().isoformat()
        indexnow([f"{SITE}/recall/{r['slug']}/" for r in rows if r.get("first_seen") == today])


if __name__ == "__main__":
    main()
