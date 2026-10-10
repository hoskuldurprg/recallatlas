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
    kw.setdefault("headers", UA)  # callers may pass their own (AU/NZ sites want a browser UA)
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=60, **kw)
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

def opt(**k):
    """Optional fields: only those with a value (keeps archive rows small)."""
    return {key: v for key, v in k.items() if v}


def rec(**k):
    """Normalized record."""
    k.setdefault("brand", "")
    k.setdefault("hazard", "")
    k.setdefault("severity", "")
    k.setdefault("image", "")
    k["title"] = clean(k.get("title"), 170)
    k["hazard"] = clean(k.get("hazard"), 220)
    return k


# ---------------------------------------------------------------- product identifiers
# Optional field "ids" on a recall: {"model": [...], "barcode": [...], "batch": [...], "listing": [...]}.
# Kept in the archive for matching (app watchlists, product check); not shipped in the 60-day site file.
ID_KINDS = ("model", "barcode", "batch", "listing")
ID_MAX, ID_LEN = 40, 60
NOT_A_CODE = {"n/a", "na", "none", "unknown", "all", "all lots", "various", "not known", "-", "0"}


def ids_of(**kinds):
    """Clean lists of identifiers per kind -> {"model": [...], ...} or None when there are none."""
    out = {}
    for k in ID_KINDS:
        seen, vals = set(), []
        for v in kinds.get(k) or []:
            v = clean(v)
            if k == "barcode":
                v = re.sub(r"[\s-]", "", v)
                if not re.fullmatch(r"\d{8}|\d{12,14}", v): continue
            if not v or v.lower() in NOT_A_CODE or len(v) > ID_LEN: continue
            if v.lower() not in seen:
                seen.add(v.lower()); vals.append(v)
        if vals: out[k] = vals[:ID_MAX]
    return out or None


def split_codes(values, seps=r"[;,\n]+"):
    """'A1, A2; A3' -> ['A1', 'A2', 'A3'] (for fields that pack several codes into one string)."""
    out = []
    for v in values:
        out += [x.strip() for x in re.split(seps, str(v or "")) if x.strip()]
    return out


UPC_RX = re.compile(r"\b(?:UPC|EAN|GTIN|barcode)s?\b[^0-9]{0,12}((?:\d[\d\s-]{6,18}\d)(?:\s*(?:,|and|&)\s*\d[\d\s-]{6,18}\d)*)", re.I)
LOT_RX = re.compile(r"\b(?:lot|batch)(?:es)?\s*(?:numbers?|nos?\.?|codes?|#)?\s*[:#]?\s*((?:[A-Z0-9][A-Z0-9-]{2,24})(?:\s*(?:,|and|&)\s*[A-Z0-9][A-Z0-9-]{2,24})*)", re.I)
MODEL_RX = re.compile(r"\b(?:model|catalog(?:ue)?|item|sku|ref(?:erence)?|part)\s*(?:numbers?|nos?\.?|#)?\s*[:#]?\s*((?:[A-Z0-9][A-Z0-9./-]{2,24})(?:\s*(?:,|and|&)\s*[A-Z0-9][A-Z0-9./-]{2,24})*)", re.I)


def codes_in(text, rx):
    found = []
    for m in rx.finditer(text or ""):
        found += [x.strip(".,:;-/") for x in re.split(r"\s*(?:,|\band\b|&)\s*", m.group(1)) if x and re.search(r"\d", x)]
    return found


def text_ids(text):
    """Identifiers written out in notice text (FDA code_info, page bodies)."""
    return ids_of(barcode=codes_in(text, UPC_RX), batch=codes_in(text, LOT_RX), model=codes_in(text, MODEL_RX))


def merge_ids(*many):
    """Combine several ids dicts (or None) into one."""
    return ids_of(**{k: [v for d in many if d for v in d.get(k, [])] for k in ID_KINDS})


ID_COLUMNS = [("barcode", r"upc|ean|gtin|bar ?code"), ("batch", r"\blot|batch|serial|^codes?$"),
              ("model", r"model|catalog|sku|item (?:no|number|#)|style|part (?:no|number)|reference")]


def table_ids(page_html):
    """Identifiers from tables whose header row names a column (UPC, Model number, Lot, Batch...)."""
    found = {k: [] for k in ID_KINDS}
    for table in re.findall(r"<table.*?</table>", page_html or "", re.S | re.I):
        rows = re.findall(r"<tr.*?</tr>", table, re.S | re.I)
        if len(rows) < 2: continue
        head = [text_of(c).lower() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", rows[0], re.S | re.I)]
        cols = {}
        for i, h in enumerate(head):
            for kind, rx in ID_COLUMNS:
                if re.search(rx, h) and i not in cols: cols[i] = kind
        if not cols:  # label/value tables: "Batch Number | 202601581A70 TCY063667"
            for row in rows:
                cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S | re.I)
                if len(cells) != 2: continue
                label = text_of(cells[0]).lower()
                kind = next((k for k, rx in ID_COLUMNS if re.search(rx, label)), None)
                if kind:
                    found[kind] += [v for v in re.split(r"[\s,;]+" if kind != "model" else r"[,;]+", text_of(cells[1]))
                                    if re.search(r"\d", v)]
            continue
        for row in rows[1:]:
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S | re.I)
            for i, kind in cols.items():
                if i >= len(cells): continue
                for part in re.split(r"<br\s*/?>|</p>|</li>|[,;\n]", cells[i], flags=re.I):
                    v = text_of(part)
                    if kind != "barcode" and (len(v.split()) > 3 or not (re.search(r"\d", v) or re.fullmatch(r"[A-Z0-9-]{3,}", v))):
                        continue
                    found[kind].append(v)
    return ids_of(**found)


def page_ids(page_html):
    """Identifiers on an official notice page: tables first, then labelled codes in the text."""
    return merge_ids(table_ids(page_html), text_ids(text_of(page_html)))


VEHICLE_RX = re.compile(r"\b((?:19|20)\d\d)\s*\|\s*([A-Z0-9][^|,;]{0,30}?)\s*\|\s*([A-Z0-9][A-Z0-9.&/+-]*(?: [A-Z0-9][A-Z0-9.&/+-]*){0,3})(?=\s*(?:[,;]|$)|\s+[A-Z]?[a-z]|\s(?:19|20)\d\d\s*\|)")


def vehicle_lines(text):
    """'2021 | FORD | EXPLORER, 2021 | LINCOLN | AVIATOR' (Transport Canada pages) -> ['2021|FORD|EXPLORER', ...]."""
    out = []
    for y, make, model in VEHICLE_RX.findall(text or ""):
        v = f"{y}|{make.strip().upper()}|{model.strip().upper()}"
        if v not in out: out.append(v)
    return out[:300]


DETAIL_MAX = 60  # detail pages read per source per run (new recalls only)


def add_page_ids(rows, fetch, vehicles=False):
    """Read the official page of each new recall once and keep its identifiers."""
    n = 0
    for r in rows:
        if r["id"] in KNOWN or n >= DETAIL_MAX: continue
        n += 1
        try:
            html = fetch(r)
        except Exception as e:
            print(f"  ids {r['id']}: {e}", file=sys.stderr); continue
        ids = page_ids(html)
        if ids: r["ids"] = ids
        if vehicles and r.get("category") == "vehicles":
            v = vehicle_lines(text_of(html))
            if v: r["vehicles"] = v
        time.sleep(0.5)
    return rows


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
        url=r.get("URL"), image=first(r.get("Images"), "URL"),
        **opt(ids=ids_of(barcode=[u.get("UPC") for u in r.get("ProductUPCs") or []])))

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
        url=FDA_LINK, **opt(ids=text_ids(r.get("code_info", ""))))

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
    rows = [norm_opss(r) for r in get(url).json()["results"] if r["public_timestamp"][:10] >= since]
    body = lambda r: (get(r["url"].replace("https://www.gov.uk/", "https://www.gov.uk/api/content/")).json()
                      .get("details") or {}).get("body") or ""
    return add_page_ids(rows, body)

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
def tc_title(title, product, system):
    """Transport Canada titles are just "Transport Canada Recall - 2023582 - KIA"; build a readable one from the
    make, the vehicle type ("Car recalled by KIA") and the system involved ("Powertrain")."""
    m = re.match(r"Transport Canada Recall\s*-\s*(\d+)\s*-\s*(.+)$", title, re.I)
    if not m: return title
    num, make = m.group(1), m.group(2).strip()
    if make.isupper() and len(make) > 4: make = make.title().replace(" Inc.", " Inc.").replace(" Llc", " LLC")
    kind = (re.match(r"(.+?)\s+recalled by\b", product or "", re.I) or [None, "vehicle"])[1].strip()
    kind = " ".join(w if w.isupper() and len(w) <= 4 else w.lower() for w in kind.split())  # keep SUV, ATV, RV
    what = f": {system.strip().lower()}" if system and system.strip() else ""
    return f"{make} {kind} recall{what} (Transport Canada {num})"


def norm_canada(r):
    title = clean(r["Title"])
    org = r.get("Organization", "")
    issue = r.get("Issue", "")
    if org == "TC":
        title = tc_title(title, clean(r.get("Product")), clean(issue))
        if issue and len(issue) < 40:  # TC gives only the system ("Powertrain"); say what that means
            issue = (f"Problem area: {clean(issue).lower()}. The Transport Canada notice lists the "
                     "affected models and model years, and what the manufacturer will do.")
    cat = ORG_CAT.get(org) or categorize(title, r.get("Product"), r.get("Issue"), hint=r.get("Category"))
    return rec(
        id=f"ca-{r['NID']}", date=r["Last updated"], country="CA",
        source={"CFIA": "CFIA", "TC": "Transport Canada"}.get(org, "Health Canada"),
        title=title, product=clean(r.get("Product"), 120), hazard=issue,
        severity=r.get("Recall class", ""), category=cat, url=r["URL"])

def crawl_canada(since, archived=False):
    url = "https://recalls-rappels.canada.ca/sites/default/files/opendata-donneesouvertes/HCRSAMOpenData.json"
    rows = get(url).json()
    out = [norm_canada(r) for r in rows
           if "/en/" in (r.get("URL") or "") and (r.get("Last updated") or "") >= since
           and (archived or r.get("Archived") != "1")]
    return add_page_ids(out, lambda r: page(r["url"]), vehicles=True)

# ---------------------------------------------------------------- EU Safety Gate
EU_API = "https://ec.europa.eu/safety-gate-alerts/public/api/notification/"
def eu_ids(d):
    p = d.get("product") or {}
    return ids_of(model=split_codes([m.get("modelType") for m in p.get("modelTypes") or []], r"[;\n]+"),
                  barcode=split_codes([b.get("barcode") for b in p.get("barcodes") or []], r"[;,/\s]+"),
                  batch=split_codes([b.get("batchNumber") for b in p.get("batchNumbers") or []]),
                  listing=[x.get("uniqueProductIdentifier") for x in d.get("onlineTraderProductIdentifierReference") or []])


def eu_counterfeit(p):
    c = p.get("isCounterfeit") or {}
    return True if str(c.get("name", "")).upper() == "YES" or str(c.get("key", "")).endswith(".yes") else None


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
        image=f"{EU_API}image/{photo_id}" if photo_id else "", **opt(ids=eu_ids(d), counterfeit=eu_counterfeit(p)))

def crawl_eu(since, max_pages=40, known=()):
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
            if f"eu-{it.get('reference')}" in known:
                continue  # already archived (backfill): skip the detail request
            try:
                d = get(f"{EU_API}{it['id']}?language=en").json()
            except Exception as e:
                print(f"  EU Safety Gate alert {it.get('id')}: {e}, skipped", file=sys.stderr)
                continue
            photo = next((ph["id"] for ph in it["product"].get("photos", []) if ph.get("mainPicture")), None)
            out.append(norm_eu(d, photo))
            time.sleep(0.3)  # be polite
    return out

EU_XML = "https://ec.europa.eu/safety-gate-alerts/api/download/weeklyReport/"
EU_CODES = {**{v.lower(): k for k, v in EU_NAMES.items()}, "czech republic": "CZ", "the netherlands": "NL",
            "northern ireland (uk)": "XI", "united kingdom (northern ireland)": "XI"}


def norm_eu_xml(n, date):
    x = lambda tag: clean(n.findtext(tag) or "")
    product, brand, specific = x("product"), x("brand"), clean(n.findtext("name") or "", 90)
    alert_url = x("reference")
    pic = n.find("pictures/picture")
    title = (product or specific) + (f" ({brand})" if brand else "") + \
        (f" · {specific}" if specific and product and specific.lower() != product.lower() else "")
    return rec(
        id=f"eu-{x('caseNumber')}", date=date, country=EU_CODES.get(x("notifyingCountry").lower(), "EU"), region="EU",
        source="EU Safety Gate", title=title, product=product or specific, brand=brand,
        hazard=x("danger") or x("riskType"), severity=x("riskType").lower(),
        category=categorize(product, specific, hint=x("category")),
        url=(alert_url + "?lang=en") if alert_url.startswith("http") else "https://ec.europa.eu/safety-gate-alerts/",
        image=(pic.text or "").strip() if pic is not None else "")


def crawl_eu_weekly(since, known=()):
    """History from Safety Gate's official weekly-report XML (one file per week since 2005)."""
    import xml.etree.ElementTree as ET
    out = []
    for wr in ET.fromstring(get(EU_XML + "list/xml/en").content).findall("weeklyReport"):
        d, m, y = (wr.findtext("publicationDate") or "").split("/")
        date = f"{y}-{int(m):02d}-{int(d):02d}"
        if date < since: continue
        try:
            root = ET.fromstring(get(wr.findtext("URL").strip()).content)
        except Exception as e:
            print(f"  EU weekly report {wr.findtext('reference')}: {e}, skipped", file=sys.stderr)
            continue
        for n in root.findall("notifications"):
            ref = (n.findtext("caseNumber") or "").strip()
            if ref and f"eu-{ref}" not in known:
                out.append(norm_eu_xml(n, date))
        time.sleep(0.5)
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

# ---------------------------------------------------------------- Australia & New Zealand
# Pages are plain HTML (no APIs), parsed with small regexes. Detail pages are only fetched for recalls not yet
# in the archive (KNOWN, filled by main()/backfill), so a normal run makes a handful of requests.
import html as _html
KNOWN = set()
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"], 1)}
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (compatible; RecallAtlas/1.0; +https://recallatlas.org)"}


def text_of(fragment):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment or "", flags=re.S)
    t = re.sub(r"<br\s*/?>|</p>|</li>", " ", t)
    return clean(_html.unescape(re.sub(r"<[^>]+>", " ", t)))


def long_date(s):
    """'2 October 2026' -> '2026-10-02' (or '' if it does not parse)."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", s or "")
    if not m or m.group(2).lower() not in MONTHS: return ""
    return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"


def page(url):
    return get(url, headers=BROWSER_UA).text


ANZ_HINTS = {  # ACCC RSS categories / Product Safety NZ categories -> our category
    "child car seats": "kids", "prams and strollers": "kids", "cots (folding or portable)": "kids",
    "change tables": "kids", "baby bathing aids": "kids", "baby feeding aids": "kids", "dummies and soothers": "kids",
    "rattles and toy teethers": "kids", "toys for babies and toddlers": "kids", "children's toys": "kids",
    "children's products": "kids", "nursery products": "kids",
    "car parts and accessories": "vehicles", "heavy vehicle parts and accessories": "vehicles",
    "dirt bikes and miniature motorbikes": "vehicles", "vehicles": "vehicles", "motor vehicles": "vehicles",
    "caravan, motorhome and camper accessories": "vehicles",
    "cosmetic products": "cosmetics", "personal care products": "cosmetics", "cleaning products": "cosmetics",
    "chemicals": "cosmetics", "clothing (daywear)": "apparel", "clothing (sleepwear)": "apparel",
    "jewellery and fashion accessories": "apparel", "clothing, footwear, and accessories": "apparel",
    "tools and machinery": "tools", "tools, equipment, and machinery": "tools", "building materials and supplies": "tools",
    "garden tools and products": "home", "indoor furniture and furnishings": "home", "kitchenware and containers": "home",
    "home and garden": "home", "household products": "home", "furniture": "home",
    "home electrical appliances": "electrical", "lithium-ion batteries": "electrical", "lighting": "electrical",
    "power supply and storage": "electrical", "heating and cooling products": "electrical", "button batteries": "electrical",
    "computers, laptops and accessories": "electrical", "phones, cameras and accessories": "electrical",
    "smart and interconnected devices": "electrical", "electric or gas products": "electrical",
    "gas products and appliances": "home", "other sports equipment": "sports", "water sports": "sports",
    "diving": "sports", "camping": "sports", "climbing and abseiling": "sports", "bicycles and scooters (push)": "sports",
    "sports, recreation, and outdoors": "sports", "food and grocery packaging": "home",
}


def anz_category(cats, *text):
    for c in cats:
        if c.strip().lower() in ANZ_HINTS: return ANZ_HINTS[c.strip().lower()]
    for c in cats:
        if re.search(r"toy|baby|child|nursery", c, re.I): return "kids"
    return categorize(*text, " ".join(cats))


# Australia: ACCC product safety recalls (consumer products incl. vehicle accessories and off-road vehicles).
ACCC_RSS = "https://www.productsafety.gov.au/rss/feed.xml/psa_recall"
ACCC_TOPICS = [10001, 10017, 10024, 10030, 10035, 10042, 10043, 10118, 10044, 10060, 10067, 10087, 10104, 10110, 40159]


def accc_field(desc, name):
    m = re.search(r'field--name-field-psa-recall-' + name + r'.*?<div class="field__item">(.*?)</div>', desc, re.S)
    return text_of(m.group(1)) if m else ""


def norm_accc(item):
    import xml.etree.ElementTree as ET
    x = lambda tag: (item.findtext(tag) or "").strip()
    desc = x("description")
    when = re.search(r'datetime="(\d{4}-\d\d-\d\d)', desc)
    date = when.group(1) if when else dt.datetime.strptime(x("pubDate")[5:16], "%d %b %Y").date().isoformat()
    cats = [c.text or "" for c in item.findall("category")]
    hazard = accc_field(desc, "hazards") or accc_field(desc, "product-defects")
    img = re.search(r'<a href="(https://www\.productsafety\.gov\.au/system/files/[^"]+\.(?:jpe?g|png))"', desc, re.I)
    title = x("title")
    return rec(id=f"accc-{x('guid')}", date=date, country="AU", source="ACCC", title=title, product=title,
               hazard=hazard, category=anz_category(cats, title, hazard), url=x("link"),
               image=_html.unescape(img.group(1)) if img else "")


def crawl_accc(since, topics=False):
    import xml.etree.ElementTree as ET
    urls = [ACCC_RSS] + ([f"{ACCC_RSS}?f%5B0%5D=topic%3A{t}" for t in ACCC_TOPICS] if topics else [])
    out = {}
    for u in urls:
        try:
            items = ET.fromstring(get(u, headers=BROWSER_UA).content).findall(".//item")
        except Exception as e:
            if u == ACCC_RSS: raise
            print(f"  ACCC topic feed skipped: {e}", file=sys.stderr); continue
        for it in items:
            r = norm_accc(it)
            if r["date"] >= since: out[r["id"]] = r
        if topics: time.sleep(1)
    return list(out.values())


# Australia: Food Standards Australia New Zealand food recalls (Australian recalls; NZ ones are on MPI).
FSANZ = "https://www.foodstandards.gov.au"


def fsanz_detail(url):
    s = page(url)
    f = lambda name: (m := re.search(r'field-' + name + r'\b.*?<div class="field-item[^"]*">(.*?)</div>', s, re.S)) and text_of(m.group(1)) or ""
    # older notices have no fields, only "<h2>Problem:</h2><p>…</p>" headings inside the summary
    h = lambda name: (m := re.search(r'<h[23][^>]*>\s*' + name + r'\s*:?(?:&nbsp;|\s)*</h[23]>\s*(.*?)(?=<h[1-6]|</div>)', s, re.S | re.I)) and text_of(m.group(1)) or ""
    return f("problem") or h("Problem"), f("food-safety-hazard") or h("Food safety hazard")


def crawl_fsanz(since, pages=1):
    out = []
    for p in range(pages):
        s = page(f"{FSANZ}/food-recalls/recall-alert" + (f"?page={p}" if p else ""))
        cards = re.findall(r'<article class="recall-card.*?</article>', s, re.S)
        if not cards: break
        for c in cards:
            href = re.search(r'recall-card__title"><a href="([^"]+)"[^>]*>(.*?)</a>', c, re.S)
            date = long_date(text_of((re.search(r'recall-card__date">(.*?)<', c, re.S) or [None, ""])[1]))
            if not href or not date or date < since: continue
            slug = href.group(1).rstrip("/").rsplit("/", 1)[-1]
            rid = f"fsanz-{slug[:90]}"
            kind = text_of((re.search(r'recall-card__type-label">(.*?)<', c, re.S) or [None, ""])[1])
            business = text_of((re.search(r'recall-card__business">(.*?)<', c, re.S) or [None, ""])[1])
            where = ", ".join(text_of(x) for x in re.findall(r'recall-card__location-pill">(.*?)<', c, re.S))
            problem = hazard = ""
            if rid not in KNOWN:
                try:
                    problem, hazard = fsanz_detail(FSANZ + href.group(1)); time.sleep(0.5)
                except Exception as e:
                    print(f"  FSANZ {slug}: {e}", file=sys.stderr)
            title = text_of(href.group(2))
            out.append(rec(id=rid, date=date, country="AU", source="FSANZ", title=title, product=title, brand=business,
                           hazard=problem or kind, severity=kind, units=where, category="food",
                           url=FSANZ + href.group(1)))
        if p: time.sleep(1)
    return out


# New Zealand: Product Safety NZ (MBIE) recalls — consumer products and vehicles.
MBIE = "https://www.productsafety.govt.nz"


def mbie_detail(url):
    s = page(url)
    m = re.search(r'recall__info--hazard">.*?recall__info-content">(.*?)</div>', s, re.S)
    t = text_of(m.group(1)) if m else ""
    t = re.sub(r"^.{0,200}?\bis recalling\b.{0,250}?\bbecause\s+", "", t)  # keep the reason, not the preamble
    return t[:1].upper() + t[1:]


def crawl_mbie(since, pages=1):
    out = []
    for p in range(pages):
        s = page(f"{MBIE}/recalls?resolved=1" + (f"&start={12 * p}" if p else ""))
        cards = re.findall(r'<article class="recall".*?</article>', s, re.S)
        if not cards: break
        older = False
        for c in cards:
            href = re.search(r'<a href="(/recalls/[^"]+)"', c)
            date = (re.search(r'datetime="(\d{4}-\d\d-\d\d)', c) or [None, ""])[1]
            if not href or not date: continue
            if date < since: older = True; continue
            slug = href.group(1).rsplit("/", 1)[-1]
            rid = f"mbie-{slug[:90]}"
            title = text_of((re.search(r'recall__title">(.*?)</h1>', c, re.S) or [None, ""])[1])
            cats = [text_of(x) for x in re.findall(r'recall__category"><a[^>]*>(.*?)</a>', c, re.S)]
            hazard = ""
            if rid not in KNOWN:
                try:
                    hazard = mbie_detail(MBIE + href.group(1)); time.sleep(0.5)
                except Exception as e:
                    print(f"  Product Safety NZ {slug}: {e}", file=sys.stderr)
            product = re.sub(r"\s+[Ss]old (at|by|through|via|online|in)\b.*$", "", title)
            out.append(rec(id=rid, date=date, country="NZ", source="Product Safety NZ", title=title, product=product,
                           hazard=hazard, category=anz_category(cats, title, hazard), url=MBIE + href.group(1)))
        if older: break
        if p: time.sleep(1)
    return out


# New Zealand: food recalls from New Zealand Food Safety (MPI). The list has no dates; each recall page does.
MPI_LIST = "https://www.mpi.govt.nz/food-safety-home/food-recalls-and-complaints/recalled-food-products/"


def mpi_detail(url):
    s = page(url)
    h1 = text_of((re.search(r"<h1[^>]*>(.*?)</h1>", s, re.S) or [None, ""])[1])
    m = re.search(r"Recalled on\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})(?:\s+by\s+([^<.]+))?", text_of(s))
    return h1, long_date(m.group(1)) if m else "", clean(m.group(2), 60) if m and m.group(2) else ""


def crawl_mpi(since, limit=20):
    s = page(MPI_LIST)
    out, seen = [], set()
    # links appear under "2026 recalls", "2025 recalls", ... headings, newest first (older years in collapsed sections)
    for year, block in re.findall(r"<h2[^>]*>\s*(\d{4}) recalls\s*</h2>(.*?)(?=<h2|$)", s, re.S):
        if int(year) < int(since[:4]): continue
        for href, name in re.findall(r'<a href="([^"]*recalled-food-products/[a-z0-9-]+)"[^>]*>(.*?)</a>', block, re.S):
            slug = href.rstrip("/").rsplit("/", 1)[-1]
            rid = f"mpi-{slug[:90]}"
            if slug in seen or rid in KNOWN: continue
            seen.add(slug)
            if len(seen) > limit: return out
            try:
                h1, date, firm = mpi_detail(href if href.startswith("http") else "https://www.mpi.govt.nz" + href)
                time.sleep(0.5)
            except Exception as e:
                print(f"  NZ Food Safety {slug}: {e}", file=sys.stderr); continue
            if date and date < since: return out  # the list is newest first: everything after this is older
            if not date: continue
            product = text_of(name)
            why = re.search(r"\b(?:recalled|is being recalled|are being recalled)\s+(?:due to|as|because)\s+(.*)$", h1, re.I)
            hazard = why.group(1) if why else ""
            out.append(rec(id=rid, date=date, country="NZ", source="NZ Food Safety", title=product or h1,
                           product=product, brand=firm, hazard=hazard[:1].upper() + hazard[1:], category="food",
                           url=href if href.startswith("http") else "https://www.mpi.govt.nz" + href))
    return out

# ---------------------------------------------------------------- main
SOURCES = [("CPSC", crawl_cpsc), ("FDA", crawl_fda), ("NHTSA", crawl_nhtsa), ("USDA FSIS", crawl_fsis),
           ("UK OPSS", crawl_opss), ("UK FSA", crawl_fsa), ("Canada", crawl_canada),
           ("EU Safety Gate", crawl_eu), ("EU RASFF", crawl_rasff),
           ("AU ACCC", crawl_accc), ("AU FSANZ", crawl_fsanz), ("NZ Product Safety", crawl_mbie), ("NZ Food Safety", crawl_mpi)]

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
            for f in ("hazard", "brand", "image", "product", "ids", "counterfeit", "vehicles"):  # keep details a lighter re-crawl did not fetch
                if not r.get(f) and old.get(f): r[f] = old[f]
        else:
            r["slug"] = f'{slugify(r["title"])}-{short_hash(r["id"])}'
            r["first_seen"] = today
            added += 1
        archive[r["id"]] = r
    return added


def with_names(r):
    r = dict(r)
    r["region"] = r.get("region") or {"US": "US", "CA": "CA", "GB": "UK", "AU": "AU", "NZ": "NZ"}.get(r["country"], "EU")
    r["countryName"] = {"US": "United States", "CA": "Canada", "GB": "United Kingdom", "AU": "Australia",
                        "NZ": "New Zealand"}.get(
        r["country"], EU_NAMES.get(r["country"], r["country"]))
    return r


def window(archive, since, ok, errors):
    rows = sorted(({k: v for k, v in with_names(r).items() if k not in ("ids", "vehicles")} for r in archive.values() if r["date"] >= since),
                  key=lambda r: (r["date"], r["id"]), reverse=True)[:MAX_ITEMS]
    counts = {name: sum(1 for r in rows if r.get("feed") == name) for name, _ in SOURCES}
    return {"updated": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
            "sources": counts, "count": len(rows), "stale_sources": errors, "recalls": rows}


def main():
    today = dt.date.today().isoformat()
    since = (dt.date.today() - dt.timedelta(days=DAYS_BACK)).isoformat()
    archive = load_archive()
    KNOWN.update(k for k, r in archive.items() if r.get("hazard"))  # recalls without a hazard get their detail page read again
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
