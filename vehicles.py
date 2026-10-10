#!/usr/bin/env python3
"""Vehicle make / model / year data for car watch (app) and future site pages. Run weekly by "Vehicle recall data".

US: NHTSA's flat file of recalls since 2010 (one row per campaign x make x model x year). Written as
    data/enrich/nhtsa.json ({"nhtsa-<campaign>": {"vehicles": ["2021|FORD|EXPLORER", ...]}}), which the crawler merges
    into the matching archive rows like the other catch-up files. Year 9999 (unknown, e.g. equipment) is kept as "".
UK: DVSA's vehicle recalls file (make, model, build dates, VIN ranges). The UK has no vehicle recalls in the archive
    yet, so this is kept as its own table: data/vehicles/uk-dvsa.json (one entry per recall number, newest first).
Canada: comes from Transport Canada's recall pages (crawler and enrich_ids.py), not from here.
"""
import csv, io, json, re, sys, zipfile, datetime as dt
from collections import defaultdict
from pathlib import Path
import crawl as C

ROOT = Path(__file__).parent
NHTSA_ZIP = "https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_POST_2010.zip"
DVSA_CSV = "https://www.check-vehicle-recalls.service.gov.uk/documents/RecallsFile.csv"
SINCE_YEAR = 2015  # UK recalls launched from this year on


def us():
    z = zipfile.ZipFile(io.BytesIO(C.get(NHTSA_ZIP, headers=C.BROWSER_UA).content))
    text = z.read(z.namelist()[0]).decode("latin-1")
    archive_ids = {k for k, r in C.load_archive().items() if r.get("feed") == "NHTSA"}
    out = defaultdict(list)
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) < 5: continue
        rid = f"nhtsa-{f[1].strip()}"
        if rid not in archive_ids: continue          # only recalls we publish (2021 onward)
        year = f[4].strip()
        year = "" if year in ("9999", "0", "") else year
        v = f"{year}|{f[2].strip().upper()}|{f[3].strip().upper()}"
        if v not in out[rid]: out[rid].append(v)
    data = {k: {"vehicles": sorted(v)[:500]} for k, v in out.items()}
    (ROOT / "data" / "enrich").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "enrich" / "nhtsa.json").write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    print(f"US: {len(data)} of {len(archive_ids)} NHTSA recalls with make/model/year, "
          f"{sum(len(v['vehicles']) for v in data.values())} vehicle lines")


def uk_date(s):
    try:
        return dt.datetime.strptime(s.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return ""


def make_name(s):
    """'MERCEDES-BENZ CARS UK LTD' -> 'MERCEDES-BENZ', 'FORD MOTOR COMPANY LTD' -> 'FORD' (DVSA lists the UK importer)."""
    s = re.sub(r"\s*\(.*?\)", "", C.clean(s).upper())
    s = re.split(r"\s+(?:CARS|MOTOR|MOTORS|AUTOMOBILES|\(UK\)|UK|GB|LTD|LIMITED|PLC|GMBH|AG|S\.?P\.?A|INC|CO\b|COMPANY|GROUP)\b", s)[0]
    return s.strip(" ,.-") or C.clean(s).upper()


def uk():
    text = C.get(DVSA_CSV, headers=C.BROWSER_UA).content.decode("utf-8-sig", "replace")
    recalls = {}
    for row in csv.DictReader(io.StringIO(text)):
        num = (row.get("Recalls Number") or "").strip()
        date = uk_date(row.get("Launch Date") or "")
        if not num or not date or int(date[:4]) < SINCE_YEAR: continue
        r = recalls.setdefault(num, {
            "id": num, "date": date, "make": make_name(row.get("Make")), "maker": C.clean(row.get("Make")),
            "concern": C.clean(row.get("Concern"), 160), "defect": C.clean(row.get("Defect"), 300),
            "remedy": C.clean(row.get("Remedy"), 300), "models": []})
        m = {"model": C.clean(row.get("Model") or row.get("Recalls Model Information"), 80).upper(),
             "from": uk_date(row.get("Build Start") or ""), "to": uk_date(row.get("Build End") or "")}
        if m["model"] and m not in r["models"]: r["models"].append(m)
    rows = sorted(recalls.values(), key=lambda r: (r["date"], r["id"]), reverse=True)
    (ROOT / "data" / "vehicles").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "vehicles" / "uk-dvsa.json").write_text(
        "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows) + "\n]\n")
    print(f"UK: {len(rows)} DVSA recalls since {SINCE_YEAR}, {sum(len(r['models']) for r in rows)} model lines")


if __name__ == "__main__":
    failed = []
    for name, fn in (("US", us), ("UK", uk)):
        try:
            fn()
        except Exception as e:
            failed.append(name)
            print(f"{name}: FAILED {e}", file=sys.stderr)
    sys.exit(1 if len(failed) == 2 else 0)
