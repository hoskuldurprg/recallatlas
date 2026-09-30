#!/usr/bin/env python3
"""
Recall crawler: pulls the latest official recalls from government sources,
normalizes them into one schema, and writes data/recalls.json.

Sources (all official, public, no API key needed):
  US  - CPSC consumer products        saferproducts.gov REST API
  US  - FDA food / drugs / devices    api.fda.gov enforcement reports
  UK  - OPSS product safety alerts    gov.uk search API
  UK  - FSA food alerts               data.food.gov.uk
  CA  - Health Canada / CFIA / TC     recalls-rappels.canada.ca open data
  EU  - Safety Gate (27 EU + EEA)     ec.europa.eu public API

Run:  python crawl.py            (writes data/recalls.json)
Deps: requests
"""
import json, re, sys, time, datetime as dt
from pathlib import Path

try:
    import requests
except ImportError:  # seed.py imports the normalizers without network deps
    requests = None

DAYS_BACK = 60          # how far back to keep recalls
MAX_ITEMS = 1500        # cap on file size
UA = {"User-Agent": "RecallAtlas/1.0 (+https://recallatlas.org)"}
OUT = Path(__file__).parent / "data" / "recalls.json"

EU_NAMES = {
 "AT":"Austria","BE":"Belgium","BG":"Bulgaria","HR":"Croatia","CY":"Cyprus","CZ":"Czechia","DK":"Denmark",
 "EE":"Estonia","FI":"Finland","FR":"France","DE":"Germany","GR":"Greece","HU":"Hungary","IE":"Ireland",
 "IT":"Italy","LV":"Latvia","LT":"Lithuania","LU":"Luxembourg","MT":"Malta","NL":"Netherlands","PL":"Poland",
 "PT":"Portugal","RO":"Romania","SK":"Slovakia","SI":"Slovenia","ES":"Spain","SE":"Sweden",
 "IS":"Iceland","NO":"Norway","LI":"Liechtenstein","XI":"Northern Ireland"}

# ---------------------------------------------------------------- helpers
def get(url, **kw):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60, **kw)
            r.raise_for_status()
            return r
        except Exception as e:
            print(f"  retry {attempt+1} {url}: {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"failed: {url}")

def clean(s, n=None):
    s = re.sub(r"[​\xa0]", " ", str(s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    if n and len(s) > n:
        s = s[: n - 1].rsplit(" ", 1)[0] + "…"
    return s

CATS = [  # first match wins; checked against title + product + hazard
 ("vehicles",  r"\b(vehicle|car|truck|suv|bus|motorcycle|tire|tyre|airbag|transport canada|nhtsa|a\.t\.v)\b"),
 ("medical",   r"\b(drug|tablet|capsule|injection|insulin|vaccine|biologic|medical device|syringe|catheter|implant|pump module|suture|mri|infusion|pharma)\b"),
 ("food",      r"\b(food|salmonella|listeria|e\. ?coli|allergen|undeclared|milk|peanut|gluten|sesame|egg|soya|snack|salsa|sprout|cheese|meat|fish|tuna|lobster|olive|chocolate|candy|beverage|drink|juice|bakery|cookie|cake|spice|coleslaw|norovirus|raspberr|mango|beans|ipa)\b"),
 ("kids",      r"\b(toy|toys|child|children|baby|infant|crib|cradle|stroller|toddler|kids|puzzle|doll|pacifier|high chair|bike helmet)\b"),
 ("electrical",r"\b(charger|battery|batteries|power bank|lithium|electric|electrical|usb|plug|socket|adapter|heater|lamp|light|led|appliance|headphone|speaker|smart glasses|shock|power supply|powerwall|welder|refrigerator|air conditioner|grill)\b"),
 ("cosmetics", r"\b(cosmetic|nail|tattoo|ink|cream|lotion|shampoo|perfume|makeup|face paint|e-cigarette|nicotine|chemical)\b"),
 ("home",      r"\b(mattress|dresser|furniture|chair|table|ladder|blanket|window|door|stove|kitchen|dining|bed|tool|pressure washer|fuel container|pool|lighter|exercise|yoga)\b"),
 ("apparel",   r"\b(clothing|jacket|anorak|hoodie|drawstring|shoe|jewel|earring|bracelet|necklace|bag|textile|rain suit)\b"),
]
def categorize(*parts, hint=""):
    text = " ".join(str(p or "") for p in parts).lower()
    h = (hint or "").lower()
    if h in {"toys"}: return "kids"
    if h in {"cosmetics"}: return "cosmetics"
    if h in {"electrical_appliances","lighting_equipment","lighting_chains","electronics","appliances"}: return "electrical"
    if h in {"clothing_textiles","jewellery"}: return "apparel"
    if h in {"chemical_products"}: return "cosmetics"
    if h in {"hobby_sports_equipment","lighters","hand_tools","furniture"}: return "home"
    for cat, rx in CATS:
        if re.search(rx[:-3] + r")(e?s)?\b", text):
            return cat
    return "other"

def rec(**k):
    """Normalized record."""
    k.setdefault("brand", "")
    k.setdefault("hazard", "")
    k.setdefault("severity", "")
    k.setdefault("image", "")
    k["title"] = clean(k.get("title"), 170)
    k["hazard"] = clean(k.get("hazard"), 220)
    return k

# ---------------------------------------------------------------- US: CPSC
def norm_cpsc(r):
    first = lambda arr, key: (arr or [{}])[0].get(key, "") if arr else ""
    hazard = first(r.get("Hazards"), "Name")
    product = first(r.get("Products"), "Name")
    return rec(
        id=f"cpsc-{r['RecallNumber']}", date=r["RecallDate"][:10],
        country="US", source="CPSC", title=r.get("Title"), product=clean(product, 120),
        brand=clean(first(r.get("Manufacturers"), "Name"), 60), hazard=hazard,
        units=clean(first(r.get("Products"), "NumberOfUnits"), 60),
        category=categorize(r.get("Title"), product, hazard),
        url=r.get("URL"), image=first(r.get("Images"), "URL"))

def crawl_cpsc(since):
    url = f"https://www.saferproducts.gov/RestWebServices/Recall?format=json&RecallDateStart={since}"
    return [norm_cpsc(r) for r in get(url).json()]

# ---------------------------------------------------------------- US: FDA
FDA_LINK = "https://www.accessdata.fda.gov/scripts/ires/index.cfm"
def norm_fda(r, kind):
    d = r["report_date"]
    firm = clean(r.get("recalling_firm"), 60)
    product = clean(r.get("product_description"), 140)
    reason = r.get("reason_for_recall", "")
    return rec(
        id=f"fda-{r['recall_number']}", date=f"{d[:4]}-{d[4:6]}-{d[6:8]}",
        country="US", source=f"FDA · {kind}", title=f"{firm} recalls {product}",
        product=product, brand=firm, hazard=reason, severity=r.get("classification", ""),
        units=clean(r.get("distribution_pattern"), 80),
        category="food" if kind == "Food" else "medical",
        url=FDA_LINK)

def crawl_fda(since):
    out, s, fails = [], since.replace("-", ""), 0
    today = dt.date.today().strftime("%Y%m%d")
    for ep, kind in [("food", "Food"), ("drug", "Drug"), ("device", "Device")]:
        url = (f"https://api.fda.gov/{ep}/enforcement.json?search=report_date:[{s}+TO+{today}]"
               f"&sort=report_date:desc&limit=300")
        try:
            out += [norm_fda(r, kind) for r in get(url).json().get("results", [])]
        except Exception as e:
            fails += 1
            print(f"  FDA {ep} skipped: {e}", file=sys.stderr)
    if fails == 3:
        raise RuntimeError("all FDA endpoints failed")
    # FDA files one row per product variant; collapse same firm+reason+date
    seen, dedup = set(), []
    for r in out:
        key = (r["brand"], r["hazard"][:80], r["date"])
        if key not in seen:
            seen.add(key); dedup.append(r)
    return dedup

# ---------------------------------------------------------------- UK: OPSS
def norm_opss(r):
    t = r["title"]
    ref = re.search(r"\(([\d-]+)\)\s*$", t)
    hazard = re.sub(r"^.*?presenting an?\s*", "", r.get("description", "")).rstrip(".")
    product = re.sub(r"^Product (Recall|Safety Report):\s*|\s*\([\d-]+\)\s*$", "", t)
    return rec(
        id=f"opss-{ref.group(1) if ref else r['link'][-20:]}", date=r["public_timestamp"][:10],
        country="GB", source="OPSS", title=product, product=product,
        hazard=hazard[:1].upper() + hazard[1:],
        severity="Recall" if t.startswith("Product Recall") else "Safety report",
        category=categorize(product, hazard), url="https://www.gov.uk" + r["link"])

def crawl_opss(since):
    url = ("https://www.gov.uk/api/search.json?filter_format=product_safety_alert_report_recall"
           "&order=-public_timestamp&count=200&fields=title,link,public_timestamp,description")
    return [norm_opss(r) for r in get(url).json()["results"] if r["public_timestamp"][:10] >= since]

# ---------------------------------------------------------------- UK: FSA
def norm_fsa(r):
    types = " ".join(r["type"]) if isinstance(r["type"], list) else r["type"]
    kind = "Allergy alert" if "AA" in types else "Product recall"
    title = r["title"]
    m = re.search(r"\b(because|due to|as)\b (.*)$", title)
    return rec(
        id=f"fsa-{r['notation']}", date=r["created"][:10], country="GB", source="FSA",
        title=title, product=title, hazard=(m.group(2) if m else "").capitalize(),
        severity=kind, category="food", url=r.get("alertURL") or r.get("@id"))

def crawl_fsa(since):
    url = f"https://data.food.gov.uk/food-alerts/id?since={since}T00:00:00&_limit=200"
    return [norm_fsa(r) for r in get(url).json()["items"]]

# ---------------------------------------------------------------- Canada
ORG_CAT = {"CFIA": "food", "TC": "vehicles", "Medical devices": "medical",
           "Drugs and health products": "medical"}
def norm_canada(r):
    title = clean(r["Title"])
    org = r.get("Organization", "")
    cat = ORG_CAT.get(org) or categorize(title, r.get("Product"), r.get("Issue"), hint=r.get("Category"))
    return rec(
        id=f"ca-{r['NID']}", date=r["Last updated"], country="CA",
        source={"CFIA": "CFIA", "TC": "Transport Canada"}.get(org, "Health Canada"),
        title=title, product=clean(r.get("Product"), 120), hazard=r.get("Issue", ""),
        severity=r.get("Recall class", ""), category=cat, url=r["URL"])

def crawl_canada(since):
    url = "https://recalls-rappels.canada.ca/sites/default/files/opendata-donneesouvertes/HCRSAMOpenData.json"
    rows = get(url).json()
    return [norm_canada(r) for r in rows
            if "/en/" in (r.get("URL") or "") and (r.get("Last updated") or "") >= since
            and r.get("Archived") != "1"]

# ---------------------------------------------------------------- EU Safety Gate
EU_API = "https://ec.europa.eu/safety-gate-alerts/public/api/notification/"
def norm_eu(d, photo_id=None):
    p = d.get("product", {})
    v = next((x for x in p.get("versions", []) if x.get("language", {}).get("key") == "EN"), {})
    name = clean(v.get("name") or p.get("nameSpecific"))
    specific = clean(p.get("nameSpecific"), 90)
    risks = ", ".join(r.get("name", "").replace("_", " ").lower() for r in d.get("risk", {}).get("riskType", []))
    rv = next((x for x in (d.get("risk", {}).get("versions") or []) if x.get("language", {}).get("key") == "EN"), {})
    brand = ", ".join(b.get("brand", "") for b in p.get("brands", []))
    cc = d.get("country", {}).get("key", "EU")
    title = name + (f" ({brand})" if brand else "") + (f" · {specific}" if specific and specific.lower() != name.lower() else "")
    return rec(
        id=f"eu-{d['reference']}", date=d["publicationDate"][:10], country=cc, region="EU",
        source="EU Safety Gate", title=title, product=name, brand=brand,
        hazard=rv.get("riskDescription") or risks.capitalize(), severity=risks,
        category=categorize(name, specific, hint=p.get("productCategory", {}).get("name", "")),
        url=f"https://ec.europa.eu/safety-gate-alerts/screen/webReport/alertDetail/{d['id']}?lang=en",
        image=f"{EU_API}image/{photo_id}" if photo_id else "")

def crawl_eu(since, max_pages=40):
    out = []
    for page in range(max_pages):
        r = requests.post(EU_API + "carousel/", json={"language": "en", "page": page},
                          headers=UA, timeout=60)
        r.raise_for_status()
        items = r.json().get("content", [])
        if not items: break
        for it in items:
            if it["publicationDate"][:10] < since:
                return out
            d = get(f"{EU_API}{it['id']}?language=en").json()
            photo = next((ph["id"] for ph in it["product"].get("photos", []) if ph.get("mainPicture")), None)
            out.append(norm_eu(d, photo))
            time.sleep(0.3)  # be polite
    return out

# ---------------------------------------------------------------- main
SOURCES = [("CPSC", crawl_cpsc), ("FDA", crawl_fda), ("UK OPSS", crawl_opss),
           ("UK FSA", crawl_fsa), ("Canada", crawl_canada), ("EU Safety Gate", crawl_eu)]

def finalize(records, sources_ok):
    for r in records:
        r.setdefault("region", {"US": "US", "CA": "CA", "GB": "UK"}.get(r["country"], "EU"))
        r["countryName"] = {"US": "United States", "CA": "Canada", "GB": "United Kingdom"}.get(
            r["country"], EU_NAMES.get(r["country"], r["country"]))
    uniq = {r["id"]: r for r in records}
    rows = sorted(uniq.values(), key=lambda r: r["date"], reverse=True)[:MAX_ITEMS]
    return {"updated": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
            "sources": sources_ok, "count": len(rows), "recalls": rows}

def main():
    since = (dt.date.today() - dt.timedelta(days=DAYS_BACK)).isoformat()
    old = json.loads(OUT.read_text()) if OUT.exists() else {"recalls": []}
    records, ok, errors = [], {}, []
    for name, fn in SOURCES:
        try:
            rows = fn(since)
            for r in rows: r["feed"] = name
            records += rows
            ok[name] = len(rows)
            print(f"{name}: {len(rows)}")
        except Exception as e:
            # keep yesterday's rows for a failing source rather than dropping them
            prev = [r for r in old["recalls"] if r.get("feed") == name]
            records += prev
            ok[name] = len(prev)
            errors.append(name)
            print(f"{name}: FAILED {e}", file=sys.stderr)
    OUT.parent.mkdir(exist_ok=True)
    data = finalize(records, ok)
    data["stale_sources"] = errors  # sources that failed this run (old rows kept)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {OUT}")

if __name__ == "__main__":
    main()
