#!/usr/bin/env python3
"""One-off probe (to be removed): which product identifiers (model, batch/lot, barcode, vehicle make/model/year)
do the official sources publish in their full notices? Writes data/probe/ids-report.json and the run summary.
Nothing here changes the archive or the site."""
import json, os, re, sys, time, collections, io, zipfile, csv
from pathlib import Path
import crawl as C

OUT = Path(__file__).parent / "data" / "probe"
OUT.mkdir(parents=True, exist_ok=True)
REPORT = {}
SNIP = 160

LABELS = {
    "model": r"\b(model|item|style|sku|art(icle)?\.?|type|reference|ref\.?|part)\s*(no\.?|number|nr\.?|#|code)?\s*[:#]",
    "barcode": r"\b(barcode|bar code|upc|ean|gtin)\b",
    "batch_lot": r"\b(batch|lot)\s*(no\.?|number|code|#)?\b",
    "date_code": r"\b(best before|use by|expiry|production date|date code|manufactured (between|on|from))\b",
    "serial": r"\bserial\s*(no\.?|number)\b",
}
DIGITS13 = re.compile(r"(?<!\d)\d{8}(?!\d)|(?<!\d)\d{12,14}(?!\d)")


def text_probe(name, docs):
    """docs = list of (id, text). Share of notices with each labelled identifier, plus snippets."""
    n = len(docs)
    res = {"n": n, "share": {}, "examples": {}}
    for k, rx in list(LABELS.items()) + [("barcode_digits", None)]:
        hits = []
        for i, t in docs:
            m = DIGITS13.search(t) if rx is None else re.search(rx, t, re.I)
            if m:
                s = max(0, m.start() - 40)
                hits.append(f"{i}: …{t[s:s + SNIP]}…")
        res["share"][k] = round(len(hits) / n, 2) if n else None
        res["examples"][k] = hits[:3]
    REPORT[name] = res
    print(f"{name}: n={n} " + " ".join(f"{k}={v}" for k, v in res["share"].items()), flush=True)


def paths(obj, prefix="", out=None):
    """Flatten a JSON record into key paths that hold a non-empty value."""
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items(): paths(v, f"{prefix}.{k}" if prefix else k, out)
    elif isinstance(obj, list):
        for v in obj: paths(v, prefix + "[]", out)
    elif obj not in (None, "", [], {}):
        out.add(prefix)
    return out


def json_probe(name, records, keep=None, sample_keys=()):
    cnt = collections.Counter()
    ex = collections.defaultdict(list)
    for r in records:
        ps = paths(r)
        cnt.update(ps)
    n = len(records)
    shares = {p: round(c / n, 2) for p, c in cnt.most_common() if (keep is None or re.search(keep, p, re.I))}

    def val(r, path):
        cur = [r]
        for part in path.split("."):
            arr = part.endswith("[]"); key = part[:-2] if arr else part
            nxt = []
            for c in cur:
                v = c.get(key) if isinstance(c, dict) else None
                if v is None: continue
                if arr and isinstance(v, list): nxt += v
                else: nxt.append(v)
            cur = nxt
        return [str(x)[:120] for x in cur if x not in (None, "")][:2]
    for p in list(shares)[:60]:
        for r in records:
            v = val(r, p)
            if v: ex[p] += v
            if len(ex[p]) >= 3: break
    REPORT[name] = {"n": n, "field_share": shares, "examples": {p: ex[p][:3] for p in shares}}
    print(f"{name}: n={n}, {len(shares)} fields", flush=True)


def safe(name, fn):
    try:
        fn()
    except Exception as e:
        REPORT[name] = {"error": f"{type(e).__name__}: {e}"[:400]}
        print(f"{name}: ERROR {e}", flush=True)


def url_probe(name, url, read_csv=False, headers=None, max_bytes=60_000_000):
    """Fetch a bulk file or API URL; report status, size, header and a few rows."""
    r = C.requests.get(url, headers=headers or C.BROWSER_UA, timeout=120, stream=True)
    info = {"url": url, "status": r.status_code, "type": r.headers.get("content-type", "")}
    if r.ok:
        data = b""
        for chunk in r.iter_content(1 << 20):
            data += chunk
            if len(data) > max_bytes: info["truncated"] = True; break
        info["bytes"] = len(data)
        if url.lower().endswith(".zip") or data[:2] == b"PK":
            z = zipfile.ZipFile(io.BytesIO(data))
            info["zip"] = z.namelist()[:10]
            data = z.read(z.namelist()[0])
        txt = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
        lines = txt.splitlines()
        info["lines"] = len(lines)
        info["head"] = [l[:400] for l in lines[:4]]
        if url.endswith(".json") or "json" in info["type"]:
            try:
                j = json.loads(txt)
                info["json_keys"] = sorted(paths(j[0] if isinstance(j, list) and j else j))[:80] if j else []
                info["json_len"] = len(j) if isinstance(j, list) else None
            except Exception as e:
                info["json_error"] = str(e)[:200]
    REPORT[name] = info
    print(f"{name}: {info.get('status')} {info.get('bytes')} bytes, {info.get('lines')} lines", flush=True)


# ---------------------------------------------------------------- products
def p_eu():
    ids = []
    for page in range(3):
        r = C.requests.post(C.EU_API + "carousel/", json={"language": "en", "page": page}, headers=C.UA, timeout=60)
        ids += [it["id"] for it in r.json().get("content", [])]
    recs = []
    for i in ids[:40]:
        try:
            recs.append(C.get(f"{C.EU_API}{i}?language=en").json()); time.sleep(0.3)
        except Exception as e:
            print("  eu", i, e)
    json_probe("eu_safety_gate_detail", recs)


def p_cpsc():
    recs = C.get("https://www.saferproducts.gov/RestWebServices/Recall?format=json&RecallDateStart=2025-01-01").json()
    json_probe("cpsc_api", recs[:300])


def p_fda():
    for kind in ("food", "device", "drug"):
        recs = C.get(f"https://api.fda.gov/{kind}/enforcement.json?limit=100&sort=report_date:desc").json()["results"]
        json_probe(f"fda_{kind}", recs)
        text_probe(f"fda_{kind}_code_info", [(r.get("recall_number"), (r.get("code_info") or "") + " " +
                                             (r.get("product_description") or "")) for r in recs])


def p_opss():
    res = C.get("https://www.gov.uk/api/search.json?filter_format=product_safety_alert_report_recall"
                "&order=-public_timestamp&count=40&fields=link").json()["results"]
    docs = []
    for r in res:
        try:
            j = C.get("https://www.gov.uk/api/content" + r["link"]).json()
            body = (j.get("details") or {}).get("body") or ""
            docs.append((r["link"].rsplit("/", 1)[-1][:50], C.text_of(body)))
            time.sleep(0.3)
        except Exception as e:
            print("  opss", e)
    text_probe("uk_opss_body", docs)


def p_canada():
    rows = C.get("https://recalls-rappels.canada.ca/sites/default/files/opendata-donneesouvertes/HCRSAMOpenData.json").json()
    REPORT["canada_opendata_keys"] = sorted(rows[0].keys()) if rows else []
    prod = [r for r in rows if "/en/" in (r.get("URL") or "") and "transport-canada" not in r.get("URL", "")]
    prod.sort(key=lambda r: r.get("Last updated") or "", reverse=True)
    docs = []
    for r in prod[:30]:
        try:
            docs.append((r["URL"].rsplit("/", 1)[-1][:50], C.text_of(C.page(r["URL"]))))
            time.sleep(0.5)
        except Exception as e:
            print("  canada", e)
    text_probe("canada_consumer_page", docs)
    veh = [r for r in rows if "transport-canada" in (r.get("URL") or "") and "/en/" in r["URL"]]
    veh.sort(key=lambda r: r.get("Last updated") or "", reverse=True)
    docs = []
    for r in veh[:10]:
        try:
            docs.append((r["URL"].rsplit("/", 1)[-1][:50], C.text_of(C.page(r["URL"]))))
            time.sleep(0.5)
        except Exception as e:
            print("  canada veh", e)
    text_probe("canada_vehicle_page", docs)
    REPORT["canada_vehicle_page"]["model_year_text"] = [
        f"{i}: " + "; ".join(re.findall(r"\b(?:19|20)\d\d\b[^.;]{0,60}", t)[:4]) for i, t in docs[:5]]


def p_accc():
    import xml.etree.ElementTree as ET
    items = ET.fromstring(C.get(C.ACCC_RSS, headers=C.BROWSER_UA).content).findall(".//item")[:25]
    docs = []
    for it in items:
        try:
            docs.append(((it.findtext("link") or "").rsplit("/", 1)[-1][:50], C.text_of(C.page(it.findtext("link")))))
            time.sleep(0.5)
        except Exception as e:
            print("  accc", e)
    text_probe("au_accc_page", docs)


def p_mbie():
    s = C.page(f"{C.MBIE}/recalls?resolved=1")
    links = list(dict.fromkeys(re.findall(r'<a href="(/recalls/[^"?]+)"', s)))[:15]
    docs = []
    for l in links:
        try:
            docs.append((l.rsplit("/", 1)[-1][:50], C.text_of(C.page(C.MBIE + l)))); time.sleep(0.5)
        except Exception as e:
            print("  mbie", e)
    text_probe("nz_mbie_page", docs)


# ---------------------------------------------------------------- vehicles: make / model / year sources
def p_nhtsa():
    recs = C.get("https://data.transportation.gov/resource/6axg-epim.json?$limit=200&$order=report_received_date DESC").json()
    json_probe("nhtsa_dataset_6axg", recs)


def p_nhtsa_api():
    j = C.get("https://api.nhtsa.gov/recalls/recallsByVehicle?make=toyota&model=rav4&modelYear=2020").json()
    REPORT["nhtsa_recallsByVehicle_rav4_2020"] = {"count": j.get("Count"), "keys": sorted(paths((j.get("results") or [{}])[0]))}


def p_nhtsa_flat():
    for u in ("https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_POST_2010.zip",
              "https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL.zip"):
        safe("nhtsa_flatfile " + u.rsplit("/", 1)[-1], lambda u=u: url_probe("nhtsa_flatfile " + u.rsplit("/", 1)[-1], u))


def p_tc():
    for u in ("https://opendatatc.blob.core.windows.net/opendatatc/vrdb_full_monthly.csv",
              "https://data.tc.gc.ca/v1.3/api/eng/vehicle-recall-database/recall/make-name/toyota/model-name/rav4/year-range/2020-2020"):
        safe("transport_canada " + u[8:60], lambda u=u: url_probe("transport_canada " + u[8:60], u))


def p_dvsa():
    for u in ("https://www.check-vehicle-recalls.service.gov.uk/documents/RecallsFile.csv",):
        safe("uk_dvsa " + u.rsplit("/", 1)[-1], lambda u=u: url_probe("uk_dvsa " + u.rsplit("/", 1)[-1], u))


def p_au_vehicles():
    safe("au_vehicles", lambda: url_probe("au_vehicles", "https://www.vehiclerecalls.gov.au/"))


if __name__ == "__main__":
    for name, fn in [("eu", p_eu), ("cpsc", p_cpsc), ("fda", p_fda), ("opss", p_opss), ("canada", p_canada),
                     ("accc", p_accc), ("mbie", p_mbie), ("nhtsa", p_nhtsa), ("nhtsa_api", p_nhtsa_api), ("nhtsa_flat", p_nhtsa_flat), ("tc", p_tc), ("dvsa", p_dvsa),
                     ("au_veh", p_au_vehicles)]:
        safe(name, fn)
    (OUT / "ids-report.json").write_text(json.dumps(REPORT, indent=1, ensure_ascii=False))
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a") as f:
            f.write("## Identifier probe\n\n")
            for k, v in REPORT.items():
                if not isinstance(v, dict): continue
                f.write(f"- **{k}**: " + json.dumps(v.get("share") or {kk: v[kk] for kk in v if kk in ("n", "status", "bytes", "lines", "error", "count")}) + "\n")
    print("done", len(REPORT))
