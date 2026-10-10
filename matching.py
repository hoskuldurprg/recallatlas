"""Recall Atlas matching engine: which archived recalls concern something a person owns.

Used by the app's watchlists and car watch, the website's "check your product" search and hubs, and later the
alerts back end. Works on archive rows (data/archive/*.json) and the UK DVSA vehicle table (data/vehicles/).

Watch items are structured (brand, product type, optional model / barcode), not free text, so the engine knows
which word is the brand. Every result has a confidence label; nothing here ever says a product is "safe".

  match_item(row, brand, ptype, model=None, barcode=None)
      -> "barcode" | "model" | "brand+type" | "accessory" | "counterfeit" | None
         barcode / model: the notice names this exact product.  brand+type: this brand recalled this kind of product,
         check your model.  accessory: a part made by someone else for this brand.  counterfeit: fake products using
         this brand.  None: no alert ("brand only" matches are deliberately not alerted).
  match_vehicle(row, make, model, year)       -> "vehicle" | "vehicle-check-year" | None   (US, Canada: row["vehicles"])
  match_uk_vehicle(dvsa, make, model, year)   -> "vehicle" | "vehicle-check-year" | None   (UK: DVSA table)
  allergens(row)   -> ["peanut", "milk", ...]  allergens a food recall is about (undeclared / allergy alerts)
  child_tags(row)  -> ["child", "car-seat", "sleep", ...]  for the baby and child hub and children's-age alerts

Tested 10 Oct 2026 against the archive: see claude/watchlist-matching-test.md in the RecallWatch project.
"""
import re, unicodedata

# ---------------------------------------------------------------- text helpers
def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", s).strip() + " "


def squash(s):
    return re.sub(r"[^a-z0-9]", "", norm(s))


def has(text_n, phrase):
    p = norm(phrase).strip()
    return bool(p) and f" {p} " in text_n


def row_text(r):
    return " ".join([r.get("title", ""), r.get("product", ""), r.get("brand", "")])


# ---------------------------------------------------------------- product types
# type -> words that mean it in recall text. Plurals ("s", "es") match automatically.
TYPES = {
    # children (also the app's gear-expiry items)
    "car seat": ["car seat", "child restraint", "booster seat", "child seat", "infant seat", "infant carrier", "carrier"],
    "stroller": ["stroller", "pushchair", "pram", "buggy", "travel system"],
    "crib": ["crib", "cot", "bassinet", "moses basket", "sleeper", "play yard", "playpen", "travel cot"],
    "baby sleeping bag": ["sleeping bag", "sleep sack", "swaddle", "baby sleeping bag"],
    "rocker": ["rocker", "bouncer", "glider", "swing"],
    "high chair": ["high chair", "highchair", "booster"],
    "baby carrier": ["baby carrier", "sling", "carrier"],
    "baby bottle": ["bottle", "teat", "nipple", "sippy cup"],
    "soother": ["soother", "pacifier", "dummy", "teether"],
    "baby monitor": ["baby monitor", "monitor"],
    "toy": ["toy", "game", "puzzle", "figure", "doll", "plush", "teddy", "playset", "rattle"],
    "chest of drawers": ["chest of drawers", "dresser", "drawer", "wardrobe"],
    "bike helmet": ["helmet"], "ski helmet": ["helmet"],
    # home safety gear (gear-expiry items)
    "smoke alarm": ["smoke alarm", "smoke detector", "smoke and carbon monoxide alarm", "fire alarm"],
    "carbon monoxide alarm": ["carbon monoxide alarm", "co alarm", "carbon monoxide detector", "co detector"],
    "fire extinguisher": ["fire extinguisher", "extinguisher", "fire spray"],
    # electrical
    "power bank": ["power bank", "powerbank", "battery pack", "portable charger", "power station"],
    "charger": ["charger", "adapter", "adaptor", "power supply", "charging"],
    "phone": ["phone", "smartphone", "mobile phone"], "laptop": ["laptop", "notebook computer"],
    "tablet": ["tablet"], "headphones": ["headphone", "earbud", "earphone", "headset"],
    "vacuum cleaner": ["vacuum", "hoover"], "air fryer": ["air fryer", "fryer", "airfryer"],
    "pressure cooker": ["pressure cooker", "multi cooker", "multicooker", "instant pot"],
    "kettle": ["kettle"], "toaster": ["toaster"], "blender": ["blender", "food processor"],
    "heater": ["heater", "radiator", "heating"], "electric blanket": ["electric blanket", "heated blanket", "heated throw"],
    "dishwasher": ["dishwasher"], "washing machine": ["washing machine", "washer"], "dryer": ["dryer", "tumble"],
    "fridge": ["fridge", "refrigerator", "freezer"], "oven": ["oven", "range", "cooker", "hob", "stove"],
    "microwave": ["microwave"], "hair dryer": ["hair dryer", "hairdryer"], "hair straightener": ["straightener", "curling"],
    "lamp": ["lamp", "light", "lighting", "led"], "extension lead": ["extension lead", "power strip", "extension cord", "socket"],
    "battery": ["battery", "batteries"], "tv": ["tv", "television"],
    # outdoor, sport, tools
    "e-bike": ["e bike", "ebike", "electric bike", "electric bicycle"], "bicycle": ["bicycle", "bike"],
    "electric scooter": ["e scooter", "electric scooter", "scooter", "kickscooter"],
    "exercise bike": ["exercise bike", "bike", "cycle"], "treadmill": ["treadmill"],
    "lawn mower": ["mower", "lawnmower"], "drill": ["drill", "driver"], "saw": ["saw"],
    "pressure washer": ["pressure washer"], "ladder": ["ladder"],
    # home
    "mattress": ["mattress"], "sofa": ["sofa", "couch", "recliner"], "chair": ["chair", "recliner"],
    "blind": ["blind", "curtain", "shade"],
    # personal care and clothing
    "perfume": ["perfume", "eau de toilette", "eau de parfum", "fragrance", "parfum", "cologne"],
    "deodorant": ["deodorant", "antiperspirant"], "shower gel": ["shower gel", "shower cream", "body wash", "shower"],
    "shampoo": ["shampoo", "conditioner"], "sunscreen": ["sunscreen", "sun cream", "spf"], "cream": ["cream", "lotion"],
    "cosmetics": ["cosmetic", "make up", "makeup", "mascara", "lipstick", "eyeliner", "nail polish"],
    "hair dye": ["hair dye", "hair colour", "hair color"], "tattoo ink": ["tattoo ink", "tattoo"],
    "clothing": ["clothing", "jacket", "coat", "hoodie", "sweater", "dress", "shirt", "trousers", "pyjama", "pajama"],
    "dress": ["dress"], "hat": ["hat", "cap"], "shoes": ["shoe", "boot", "sandal", "trainer", "sneaker", "footwear"],
    "jewellery": ["jewellery", "jewelry", "necklace", "bracelet", "earring", "ring"],
    # food and pets (match against food recalls)
    "dog food": ["dog food", "dog", "pet food"], "cat food": ["cat food", "cat", "pet food"],
}
FOOD_TYPES = {"dog food", "cat food"}
VEHICLE_WORDS = {"car", "suv", "van", "pickup", "truck", "motorcycle", "vehicle"}


def type_hit(r, text_n, ptype):
    words = TYPES.get(ptype) or [ptype]
    return any(has(text_n, w) or has(text_n, w + "s") or has(text_n, w + "es") for w in words)


# ---------------------------------------------------------------- items
def brand_hit(r, text_n, brand):
    """Brand as a whole word (or the notice's brand field); 'Apple' must not match 'Pineapple'."""
    return bool(brand) and (has(text_n, brand) or has(norm(r.get("brand", "")), brand) or has(text_n, squash(brand)))


def code_in(values, code):
    c = squash(code)
    return bool(c) and any(squash(v) == c for v in values or [])


def model_in_text(text, model):
    m = squash(model)
    if len(m) < 2 or m not in squash(text): return False
    toks = norm(text).split()
    return m in {squash(" ".join(toks[i:i + k])) for k in (1, 2, 3) for i in range(len(toks))}


def match_item(r, brand, ptype, model=None, barcode=None):
    ids = r.get("ids") or {}
    if barcode and code_in(ids.get("barcode"), barcode):
        return "barcode"
    text = row_text(r)
    tn = norm(text)
    b = brand_hit(r, tn, brand)
    distinctive = bool(model) and len(squash(model)) >= 5 and re.search(r"\d", model) and re.search(r"[a-z]", model, re.I)
    if model and (code_in(ids.get("model"), model) or model_in_text(text, model)) and (b or distinctive or not brand):
        return "model"
    if model and brand and any(make_key(line.split("|")[1]) == make_key(brand) and model_hit(line.split("|")[2], model)
                               for line in r.get("vehicles") or [] if line.count("|") >= 2):
        return "model"                                 # NHTSA child-seat / equipment recalls list brand + model
    if not b:
        return None
    if r.get("category") in ("medical", "food") and ptype not in FOOD_TYPES:
        return None                                    # e.g. Samsung X-ray systems, Philips Respironics
    bn = norm(brand).strip()
    t = type_hit(r, tn, ptype)
    if re.search(rf" (for|compatible with|replacement for|fits|suitable for)( the| your| use with)? {re.escape(bn)} ", tn):
        return "accessory" if t else None              # third-party part made for the brand
    if r.get("counterfeit") or re.search(r" (counterfeit|fake|imitation) ", tn):
        return "counterfeit" if t else None
    return "brand+type" if t else None


# ---------------------------------------------------------------- vehicles
MAKE_ALIASES = {"VW": "VOLKSWAGEN", "MERCEDES": "MERCEDES-BENZ", "MERCEDES BENZ": "MERCEDES-BENZ",
                "MERCEDES-BENZ VANS": "MERCEDES-BENZ", "MERCEDES BENZ VANS": "MERCEDES-BENZ", "CHEVY": "CHEVROLET",
                "LANDROVER": "LAND ROVER", "RANGE ROVER": "LAND ROVER", "JLR": "LAND ROVER", "JAGUAR LAND ROVER": "LAND ROVER",
                "VAUXHALL": "VAUXHALL", "OPEL": "OPEL", "MINI": "MINI", "BMW MINI": "MINI", "HARLEY": "HARLEY-DAVIDSON",
                "DS": "DS", "FIAT CHRYSLER": "FIAT", "STELLANTIS": "FIAT", "GM": "GENERAL MOTORS"}
MAKE_SUFFIX = re.compile(r"\s+(?:CARS|MOTOR|MOTORS|AUTOMOBILES|UK|GB|LTD|LIMITED|PLC|GMBH|AG|SPA|S\.P\.A|INC|CO|COMPANY|"
                         r"GROUP|NORTH AMERICA|AMERICA|USA|CANADA|EUROPE|VANS|TRUCKS?)\b.*$")


def make_key(s):
    s = re.sub(r"\s*\(.*?\)", "", str(s or "").upper()).strip()
    s = MAKE_ALIASES.get(s, s)
    s = MAKE_SUFFIX.sub("", s).strip(" ,.-")
    return MAKE_ALIASES.get(s, s)


def model_hit(line_model, model):
    """'RAV4' matches 'RAV4', 'RAV4 PRIME', 'RAV4 HYBRID'; 'CR-V' matches 'CRV'."""
    a, b = squash(line_model), squash(model)
    return bool(b) and (a == b or a.startswith(b))


def match_vehicle(r, make, model, year=None):
    """US (NHTSA) and Canada (Transport Canada) rows carry "vehicles": ["2021|FORD|EXPLORER", ...].
    Rows without that list (EU Safety Gate cars) match only when the notice text names the make and the model."""
    if not r.get("vehicles"):
        if r.get("category") != "vehicles": return None
        text = row_text(r)
        mk = make_key(make)
        return "vehicle-check-year" if (has(norm(text), mk) or has(norm(r.get("brand", "")), mk)) and model and model_in_text(text, model) else None
    best = None
    mk = make_key(make)
    for line in r.get("vehicles") or []:
        y, lmake, lmodel = (line.split("|") + ["", "", ""])[:3]
        if make_key(lmake) != mk or not model_hit(lmodel, model): continue
        if not y or not year:
            best = best or "vehicle-check-year"
        elif str(year) == y:
            return "vehicle"
    return best


def match_uk_vehicle(d, make, model, year=None):
    """UK DVSA recalls list models with build dates; a car's year is matched against the build years."""
    if make_key(d.get("make")) != make_key(make): return None
    best = None
    for m in d.get("models") or []:
        if not model_hit(m.get("model"), model): continue
        lo, hi = (m.get("from") or "")[:4], (m.get("to") or "")[:4]
        if not year or not lo:
            best = best or "vehicle-check-year"
        elif lo <= str(year) <= (hi or lo):
            return "vehicle"
        elif int(lo) - 1 <= int(year) <= int(hi or lo) + 1:
            best = best or "vehicle-check-year"     # built late in the previous year / sold the next year
    return best


# ---------------------------------------------------------------- tags for hubs and safety-profile alerts
ALLERGENS = {
    "peanut": r"peanuts?|groundnuts?",
    "tree nuts": r"tree nuts?|almonds?|hazelnuts?|walnuts?|cashews?|pecans?|pistachios?|brazil nuts?|macadamias?|nuts",
    "milk": r"milk|dairy|lactose|casein|whey",
    "egg": r"eggs?",
    "gluten": r"gluten|wheat|barley|rye|spelt|oats?",
    "sesame": r"sesame",
    "soy": r"soy|soya|soybeans?",
    "fish": r"fish|anchov(?:y|ies)|tuna|salmon|cod",
    "shellfish": r"shellfish|crustaceans?|shrimps?|prawns?|crabs?|lobsters?|molluscs?|mussels?|oysters?|clams?|squid",
    "mustard": r"mustard", "celery": r"celery|celeriac", "lupin": r"lupin|lupine",
    "sulphites": r"sulphites?|sulfites?|sulphur dioxide|sulfur dioxide",
}
ALLERGY_CONTEXT = re.compile(r"undeclared|not declared|allerg|may contain|not mentioned on the label|"
                             r"not listed|does not (?:declare|list)|contains? (?:undeclared )?", re.I)


def allergens(r):
    """Allergens a food recall is about. Only when the notice is about an allergen (undeclared, allergy alert)."""
    if r.get("category") != "food": return []
    text = " ".join([r.get("title", ""), r.get("hazard", ""), r.get("severity", "")])
    if not (ALLERGY_CONTEXT.search(text) or "allergy alert" in str(r.get("severity", "")).lower()): return []
    m = ALLERGY_CONTEXT.search(text)
    focus = text[m.start():] if m else text                    # words after "undeclared ..." name the allergen
    found = [a for a, rx in ALLERGENS.items() if re.search(rf"\b(?:{rx})\b", focus, re.I)]
    if "peanut" in found and "tree nuts" in found and not re.search(r"\b(?:tree nuts?|almond|hazelnut|walnut|cashew|pecan|pistachio|brazil|macadamia)", focus, re.I):
        found.remove("tree nuts")                              # "peanuts" alone, not "nuts"
    return found


CHILD_TAGS = [
    ("car-seat", r"car seats?|child restraints?|booster seats?|infant carriers?|child seats?"),
    ("sleep", r"cribs?|cots?|bassinets?|moses baskets?|sleep(?:er|ing bag|sack)s?|mattress|play yards?|travel cots?|inclined sleep"),
    ("stroller", r"strollers?|pushchairs?|prams?|buggy|buggies"),
    ("button-battery", r"button (?:cell|batter)|coin (?:cell|batter)"),
    ("magnets", r"magnets?|magnetic"),
    ("small-parts", r"small parts?|chok(?:e|ing)"),
    ("strangulation", r"strangulation|cords?|drawstrings?"),
]
CHILD_WORDS = re.compile(r"\b(?:baby|babies|infant|toddler|child|children|kids?|toy|toys|nursery|newborn)\b", re.I)


def child_tags(r):
    text = " ".join([r.get("title", ""), r.get("product", ""), r.get("hazard", "")])
    if re.search(r"\badults?\b", r.get("title", ""), re.I) and r.get("category") != "kids":
        return []                                     # e.g. adult bed rails that mention a child entrapment risk
    is_child = r.get("category") == "kids" or bool(CHILD_WORDS.search(text))
    tags = [t for t, rx in CHILD_TAGS if re.search(rf"\b(?:{rx})\b", text, re.I)]
    if tags and tags != ["small-parts"] and tags != ["strangulation"] and tags != ["magnets"]:
        is_child = is_child or bool({"car-seat", "sleep", "stroller"} & set(tags))
    return (["child"] + tags) if is_child else []


if __name__ == "__main__":
    # Quick check from the command line, e.g.:
    #   python matching.py item Britax "car seat"          python matching.py car Toyota RAV4 2020
    #   python matching.py uk-car Ford Kuga 2020           python matching.py allergen peanut
    import json, sys
    from pathlib import Path
    import crawl
    arch = crawl.load_archive(); crawl.apply_enrich(arch)
    kind, args = sys.argv[1], sys.argv[2:]
    if kind == "uk-car":
        rows = json.loads((Path(__file__).parent / "data" / "vehicles" / "uk-dvsa.json").read_text())
        hits = [(match_uk_vehicle(d, *args[:2], args[2] if len(args) > 2 else None), d["date"], d["id"], d["concern"]) for d in rows]
    else:
        test = {"item": lambda r: match_item(r, *args),
                "car": lambda r: match_vehicle(r, args[0], args[1], args[2] if len(args) > 2 else None),
                "allergen": lambda r: "allergen" if args[0] in allergens(r) else None,
                "child": lambda r: "child" if args[0] in child_tags(r) else None}[kind]
        hits = [(test(r), r["date"], r["id"], r["title"][:90]) for r in arch.values()]
    hits = sorted((h for h in hits if h[0]), key=lambda h: h[1], reverse=True)
    for h in hits[:25]: print(*h, sep="  ")
    print(f"{len(hits)} matches")
