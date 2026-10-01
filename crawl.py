#!/usr/bin/env python3
"""
Recall crawler: pulls the latest official recalls from government sources,
normalizes them into one schema, and writes data/recalls.json.

Sources (all official, public, no API key needed):
  US  - CPSC consumer products        saferproducts.gov REST API
  US  - FDA food / drugs / devices    api.fda.gov enforcement reports
  US  - NHTSA vehicles, car seats     data.transportation.gov (Socrata)
  US  - USDA FSIS meat & poultry      fsis.usda.gov recall API
  UK  - OPSS product safety alerts    gov.uk search API
  UK  - FSA food alerts               data.food.gov.uk
  CA  - Health Canada / CFIA / TC     recalls-rappels.canada.ca open data
  EU  - Safety Gate (27 EU + EEA)     ec.europa.eu public API
  EU  - RASFF food alerts             webgate.ec.europa.eu/rasff-window consumer API

Run:  python crawl.py   (updates data/archive/*.json, the permanent store, and
                         data/recalls.json, the last 60 days used by list pages)
Deps: requests
"""
import json, re, sys, time, datetime as dt
from pathlib import Path

try:
    import requests
except ImportError:  # lets tests import the normalizers without network deps
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
 "IS":"Iceland","NO":"Norway","LI":"Liechtenstein","CH":"Switzerland","XI":"Northern Ireland"}

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

CATS = [  # first match wins; checked against title + product + hazard (plurals match too)
 ("vehicles",  r"\b(vehicle|car|truck|suv|bus|motorcycle|motor home|trailer|tire|tyre|airbag|transport canada|nhtsa|a\.t\.v|snowmobile|scooter|motorbike|dirt bike)\b"),
 ("medical",   r"\b(drug|tablet|capsule|injection|insulin|vaccine|biologic|medical device|syringe|catheter|implant|pump module|suture|mri|infusion|pharma|stent|occluder|glucose|walker|hearing aid|contact lens|surgical)\b"),
 ("food",      r"\b(food|salmonella|listeria|e\. ?coli|allergen|undeclared|milk|peanut|gluten|sesame|egg|soya|soy|snack|salsa|sprout|cheese|meat|pork|beef|chicken|poultry|sausage|fish|tuna|lobster|shrimp|olive|chocolate|candy|beverage|drink|juice|bakery|bread|cookie|cake|spice|coleslaw|norovirus|raspberr|berr|mango|beans|ipa|beer|wine|flour|rice|noodle|sauce|seasoning|supplement|vitamin|infant formula|botulism|mycotoxin|aflatoxin|pesticide|ethylene oxide|probiotic|herbal)\b"),
 ("kids",      r"\b(toy|toys|child|children|baby|babies|infant|crib|cradle|stroller|pram|toddler|kids|kid|puzzle|doll|pacifier|teether|rattle|high chair|playpen|play pen|busy board|squishy|slime|swim ring|swim seat|float|bath seat|bassinet|carrier|car seat|sand art|coloured sand|colored sand|school|princess|dress-up|costume|swing set|safety lock|cabinet lock|night light|balloon|water bead|sensory|play gym|buggy|dough|fidget|anti-stress|jumper|craft)\b"),
 ("sports",    r"\b(bike|bicycle|e-bike|ebike|helmet|treadmill|exercise|fitness|yoga|pilates|weight plate|barbell|dumbbell|kettlebell|buoyancy|life jacket|lifejacket|swim|dive|diving|regulator|climbing|quickdraw|carabiner|harness|hockey|visor|ski|skate|skateboard|trampoline|handlebar|camping|tent|kayak|paddle|golf|football|basketball|dart)\b"),
 ("tools",     r"\b(drill|saw|saw blade|grinder|angle grinder|sander|polisher|polishing machine|trimmer|brush cutter|mower|lawn|chainsaw|jack|ladder|welder|laser|engraving|cutter|harvester|tractor|compressor|generator|pressure washer|nail gun|leaf blower|blower|grease gun|mixer|kneading|glove|mask|respirator|earmuff|ear defender|goggles|protective)\b"),
 ("electrical",r"\b(charger|battery|batteries|power bank|powerbank|power station|hand warmer|adaptor|luminaire|circuit breaker|circuit-breaker|web cam|lithium|electric|electrical|usb|plug|socket|extension lead|adapter|heater|lamp|light|lighting|led|appliance|headphone|earbud|speaker|smart glasses|webcam|camera|pager|projector|shock|power supply|powerwall|refrigerator|fridge|freezer|air conditioner|fan|kettle|toaster|blender|hair dryer|straightener|sleep machine|grill|range|oven|microwave|dishwasher|washing machine|dryer|vacuum)\b"),
 ("cosmetics", r"\b(cosmetic|nail|tattoo|ink|cream|lotion|shampoo|conditioner|mousse|hand wash|soap|micellar|cleansing|sunscreen|perfume|makeup|mascara|lipstick|face paint|hair dye|e-cigarette|vape|nicotine|chemical|detergent|cleaner|air freshener|aer spray|bleach|wipe|spray|hyaluronic)\b"),
 ("home",      r"\b(mattress|dresser|furniture|chair|table|shelf|cabinet|blind|shade|curtain|blanket|duvet|pillow|window|door|doorstop|draught excluder|stove|kitchen|dining|cookware|pan|pot|glass|mug|bottle|pepper mill|bed|sofa|sauna|pool|lighter|candle|fire extinguisher|fire spray|smoke alarm|carbon monoxide|solar collector|boiler|fuel container|garden|shower|jug|stairway|fire alarm|plant)\b"),
 ("apparel",   r"\b(clothing|jacket|anorak|coat|hoodie|sweater|pyjama|pajama|nightwear|bathrobe|robe|drawstring|shoe|boot|sandal|jewel|jewellery|jewelry|earring|bracelet|necklace|ring|bag|handbag|textile|rain suit|hat|scarf|sunglasses)\b"),
]
HINTS = {  # EU Safety Gate productCategory / Canada category -> our category
 "toys": "kids", "childcare_articles_and_children_equipment": "kids", "toys and games": "kids",
 "cosmetics": "cosmetics", "chemical_products": "cosmetics",
 "electrical_appliances": "electrical", "lighting_equipment": "electrical", "lighting_chains": "electrical",
 "electronics": "electrical", "appliances": "electrical", "communication_and_media_equipment": "electrical",
 "clothing_textiles": "apparel", "jewellery": "apparel", "fashion_items": "apparel",
 "hobby_sports_equipment": "sports", "sports and recreation": "sports",
 "hand_tools": "tools", "machinery": "tools", "protective_equipment": "tools", "personal_protective_equipment": "tools",
 "lighters": "home", "furniture": "home", "kitchen_cooking_accessories": "home", "decorative_articles": "home",
 "motor_vehicles": "vehicles", "food_imitating_products": "kids",
}
def categorize(*parts, hint=""):
    h = (hint or "").lower()
    if h in HINTS:
        return HINTS[h]
    text = " ".join(str(p or "") for p in parts).lower()
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
    """Safety Gate pages sometimes fail on one broken record (HTTP 404); skip that page or item
    and carry on, giving up only after 5 failed pages in a row."""
    out, bad = [], 0
    for page in range(max_pages):
        r = requests.post(EU_API + "carousel/", json={"language": "en", "page": page},
                          headers=UA, timeout=60)
        if not r.ok:
            bad += 1
            print(f"  EU Safety Gate page {page}: HTTP {r.status_code}, skipped", file=sys.stderr)
            if bad >= 5: raise RuntimeError(f"5 failed pages in a row (last HTTP {r.status_code})")
            continue
        bad = 0
        items = r.json().get("content", [])
        if not items: break
        for it in items:
            if it["publicationDate"][:10] < since:
                return out
            try:
                d = get(f"{EU_API}{it['id']}?language=en").json()
            except Exception as e:
                print(f"  EU Safety Gate alert {it.get('id')}: {e}, skipped", file=sys.stderr)
                continue
            photo = next((ph["id"] for ph in it["product"].get("photos", []) if ph.get("mainPicture")), None)
            out.append(norm_eu(d, photo))
            time.sleep(0.3)  # be polite
    return out

# ---------------------------------------------------------------- US: NHTSA (vehicles, tires, car seats, equipment)
def norm_nhtsa(r):
    typ = r.get("recall_type", "Vehicle")
    flags = []
    if r.get("do_not_drive") == "Yes": flags.append("Do not drive")
    if r.get("fire_risk_when_parked") == "Yes": flags.append("Park outside")
    return rec(
        id=f"nhtsa-{r['nhtsa_id']}", date=r["report_received_date"][:10], country="US",
        source="NHTSA", title=f"{clean(r.get('manufacturer'), 60)}: {r.get('subject', '')}",
        product=clean(r.get("component"), 80), brand=clean(r.get("manufacturer"), 60),
        hazard=r.get("consequence_summary") or r.get("defect_summary", ""),
        severity=" · ".join(flags) or typ,
        units=(f"{int(r['potentially_affected']):,} affected" if str(r.get("potentially_affected", "")).isdigit() else ""),
        category="kids" if typ == "Child Seat" else "vehicles",
        url=(r.get("recall_link") or {}).get("url") or f"https://www.nhtsa.gov/recalls?nhtsaId={r['nhtsa_id']}")

def crawl_nhtsa(since):
    url = ("https://data.transportation.gov/resource/6axg-epim.json"
           f"?$where=report_received_date>='{since}'&$order=report_received_date DESC&$limit=2000")
    return [norm_nhtsa(r) for r in get(url).json()]

# ---------------------------------------------------------------- US: USDA FSIS (meat, poultry, eggs)
def norm_fsis(r):
    reasons = ", ".join(r.get("field_recall_reason") or [])
    states = r.get("field_states") or []
    num = r.get("field_recall_number") or re.sub(r"\W+", "-", r.get("field_title", ""))[:40]
    return rec(
        id=f"fsis-{num}", date=r["field_recall_date"][:10], country="US", source="USDA FSIS",
        title=r.get("field_title"), product=clean("; ".join(r.get("field_product_items") or []), 140),
        brand=clean(", ".join(r.get("field_establishment") or []), 60), hazard=reasons,
        severity=r.get("field_recall_classification") or r.get("field_recall_type", ""),
        units=("Nationwide" if "Nationwide" in states else clean(", ".join(states), 80)),
        category="food", url=(r.get("field_recall_url") or "").replace("http://", "https://"))

def crawl_fsis(since):
    hdr = {**UA, "User-Agent": "Mozilla/5.0 (compatible; RecallAtlas/1.0; +https://recallatlas.org)",
           "Accept": "application/json"}
    r = requests.get("https://www.fsis.usda.gov/fsis/api/recall/v/1", headers=hdr, timeout=120)
    r.raise_for_status()
    return [norm_fsis(x) for x in r.json()
            if (x.get("field_recall_date") or "") >= since and x.get("langcode") == "English"]

# ---------------------------------------------------------------- EU: RASFF food alerts for consumers
RASFF = "https://webgate.ec.europa.eu/rasff-window/"
def norm_rasff(n, countries):
    d, m, y = n["ecValidationDate"][:10].split("-")
    risk = (n.get("riskDecision") or {}).get("description", "")
    ptype = (n.get("productType") or {}).get("description", "food")
    return rec(
        id=f"rasff-{n['reference']}", date=f"{y}-{m}-{d}",
        country=(n.get("notifyingCountry") or {}).get("isoCode", "EU"), region="EU",
        countries=sorted(countries), source="EU RASFF", title=n.get("subject", ""),
        product=(n.get("productCategory") or {}).get("description", ""),
        hazard=f"{(n.get('notificationClassification') or {}).get('description', '').capitalize()}. "
               f"Product category: {(n.get('productCategory') or {}).get('description', '')}.",
        severity=f"{risk} risk" if risk and "risk" not in risk else risk,
        category="home" if ptype == "food contact material" else "food",
        url=f"{RASFF}screen/notification/{n['notifId']}")

def crawl_rasff(since):
    orgs = get(RASFF + "backend/public/organization/single/market/list/en/").json()["organizations"]
    found, where = {}, {}
    for o in orgs:
        if o["id"] == -1 or not o.get("numberOfNotifications"):
            continue
        body = {"parameters": {"pageNumber": 1, "itemsPerPage": 100}, "organizationId": str(o["id"])}
        r = requests.post(RASFF + "backend/public/consumer/search/en/", json=body, headers=UA, timeout=60)
        r.raise_for_status()
        for n in r.json().get("notifications", []):
            found[n["notifId"]] = n
            where.setdefault(n["notifId"], set()).add(o["code"])
        time.sleep(0.5)
    out = [norm_rasff(n, where[i]) for i, n in found.items()]
    return [x for x in out if x["date"] >= since]

# ---------------------------------------------------------------- main
SOURCES = [("CPSC", crawl_cpsc), ("FDA", crawl_fda), ("NHTSA", crawl_nhtsa), ("USDA FSIS", crawl_fsis),
           ("UK OPSS", crawl_opss), ("UK FSA", crawl_fsa), ("Canada", crawl_canada),
           ("EU Safety Gate", crawl_eu), ("EU RASFF", crawl_rasff)]

ARCHIVE = Path(__file__).parent / "data" / "archive"


def slugify(text, n=70):
    import unicodedata
    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:n].rstrip("-") or "recall"


def short_hash(s):
    import hashlib
    return hashlib.sha1(s.encode()).hexdigest()[:6]


def load_archive():
    """All recalls ever seen, keyed by id. Stored as one JSON file per month (YYYY-MM.json)."""
    rows = {}
    for f in sorted(ARCHIVE.glob("*.json")):
        for r in json.loads(f.read_text()):
            rows[r["id"]] = r
    return rows


def save_archive(rows):
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    months = {}
    for r in rows.values():
        months.setdefault(r["date"][:7], []).append(r)
    for f in ARCHIVE.glob("*.json"):
        if f.stem not in months:
            f.unlink()
    for m, rs in months.items():
        rs.sort(key=lambda r: r["id"])
        (ARCHIVE / f"{m}.json").write_text(
            "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rs) + "\n]\n")


def merge(archive, records, today):
    """Insert new recalls and refresh changed ones. A recall keeps its URL slug and first_seen date forever."""
    added = 0
    for r in records:
        for k in ("region", "countryName"):
            r.pop(k, None)
        old = archive.get(r["id"])
        if old:
            r["slug"], r["first_seen"] = old["slug"], old["first_seen"]
        else:
            r["slug"] = f'{slugify(r["title"])}-{short_hash(r["id"])}'
            r["first_seen"] = today
            added += 1
        archive[r["id"]] = r
    return added


def with_names(r):
    r = dict(r)
    r["region"] = r.get("region") or {"US": "US", "CA": "CA", "GB": "UK"}.get(r["country"], "EU")
    r["countryName"] = {"US": "United States", "CA": "Canada", "GB": "United Kingdom"}.get(
        r["country"], EU_NAMES.get(r["country"], r["country"]))
    return r


def window(archive, since, ok, errors):
    rows = sorted((with_names(r) for r in archive.values() if r["date"] >= since),
                  key=lambda r: (r["date"], r["id"]), reverse=True)[:MAX_ITEMS]
    counts = {name: sum(1 for r in rows if r.get("feed") == name) for name, _ in SOURCES}
    return {"updated": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
            "sources": counts, "count": len(rows), "stale_sources": errors, "recalls": rows}


def main():
    today = dt.date.today().isoformat()
    since = (dt.date.today() - dt.timedelta(days=DAYS_BACK)).isoformat()
    archive = load_archive()
    if not archive and OUT.exists():  # first run after the archive was introduced: seed it
        merge(archive, json.loads(OUT.read_text())["recalls"], today)
    ok, errors = {}, []
    for name, fn in SOURCES:
        try:
            rows = fn(since)
            for r in rows: r["feed"] = name
            new = merge(archive, rows, today)
            ok[name] = len(rows)
            print(f"{name}: {len(rows)} ({new} new)")
        except Exception as e:
            errors.append(name)  # archive keeps this source's earlier rows
            print(f"{name}: FAILED {e}", file=sys.stderr)
    save_archive(archive)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(window(archive, since, ok, errors), ensure_ascii=False, separators=(",", ":")))
    print(f"archive: {len(archive)} recalls; wrote {OUT}")


if __name__ == "__main__":
    main()
