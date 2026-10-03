#!/usr/bin/env python3
"""One-off: download sample pages from Australian and New Zealand recall sources into probe/ so the
crawler can be written against real pages. Safe to delete together with .github/workflows/probe.yml."""
import json, re, urllib.parse
from pathlib import Path
import requests

OUT = Path(__file__).parent / "probe"
OUT.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (compatible; RecallAtlas/1.0; +https://recallatlas.org)"}
PAGES = {
    "au_accc_rss_p1": "https://www.productsafety.gov.au/rss/feed.xml/psa_recall?page=1",
    "au_accc_rss_p30": "https://www.productsafety.gov.au/rss/feed.xml/psa_recall?page=30",
    "au_accc_rss_vehicle_topic": "https://www.productsafety.gov.au/rss/feed.xml/psa_recall?f%5B0%5D=topic%3A10104",
    "au_vehicle_home": "https://www.vehiclerecalls.gov.au/",
    "au_accc_vehicle_rss_guess": "https://www.productsafety.gov.au/rss/feed.xml/psa_vehicle_recall",
    "au_accc_vehicle_list_guess": "https://www.productsafety.gov.au/recalls/vehicle-recalls",
    "au_fsanz_list_last": "https://www.foodstandards.gov.au/food-recalls/recall-alert?page=18",
    "nz_mbie_resolved": "https://www.productsafety.govt.nz/recalls?resolved=1",
    "nz_mbie_resolved_old": "https://www.productsafety.govt.nz/recalls?resolved=1&start=1584",
}
DETAIL = {
    "au_vehicle_home": r"https?://[^\"' ]*(?:recall|search)[^\"' ]*",
}
index = {}
for name, url in PAGES.items():
    try:
        r = requests.get(url, headers=UA, timeout=60)
        (OUT / f"{name}.html").write_text(r.text)
        index[name] = {"url": url, "status": r.status_code, "bytes": len(r.text), "type": r.headers.get("content-type")}
    except Exception as e:
        index[name] = {"url": url, "error": str(e)}
for name, pat in DETAIL.items():
    f = OUT / f"{name}.html"
    if not f.exists(): continue
    links = list(dict.fromkeys(re.findall(pat, f.read_text())))[:4]
    for i, link in enumerate(links):
        url = urllib.parse.urljoin(PAGES[name], link)
        try:
            r = requests.get(url, headers=UA, timeout=60)
            (OUT / f"{name}_detail{i}.html").write_text(r.text)
            index[f"{name}_detail{i}"] = {"url": url, "status": r.status_code, "bytes": len(r.text)}
        except Exception as e:
            index[f"{name}_detail{i}"] = {"url": url, "error": str(e)}
(OUT / "index.json").write_text(json.dumps(index, indent=1))
print(json.dumps(index, indent=1))
