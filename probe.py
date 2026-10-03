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
    "au_accc_rss": "https://www.productsafety.gov.au/rss/feed.xml/psa_recall",
    "au_accc_list": "https://www.productsafety.gov.au/recalls",
    "au_accc_list_100_p1": "https://www.productsafety.gov.au/recalls?items_per_page=100&page=1",
    "au_fsanz_list": "https://www.foodstandards.gov.au/food-recalls/recall-alert",
    "au_fsanz_list_p1": "https://www.foodstandards.gov.au/food-recalls/recall-alert?page=1",
    "au_fsanz_rss1": "https://www.foodstandards.gov.au/rss.xml",
    "au_fsanz_rss2": "https://www.foodstandards.gov.au/food-recalls/recall-alert/rss.xml",
    "nz_mbie_list": "https://www.productsafety.govt.nz/recalls",
    "nz_mbie_list_p2": "https://www.productsafety.govt.nz/recalls?start=12",
    "nz_mbie_rss": "https://www.productsafety.govt.nz/recalls/rss",
    "nz_mpi_list": "https://www.mpi.govt.nz/food-safety-home/food-recalls-and-complaints/recalled-food-products/",
}
DETAIL = {  # list page -> link pattern for detail pages to sample
    "au_accc_rss": r"https://www\.productsafety\.gov\.au/search-consumer-product-recalls/[a-z0-9-]+",
    "au_fsanz_list": r"/food-recalls/recall-alert/[a-z0-9-]+",
    "nz_mbie_list": r"/recalls/[a-z0-9-]{12,}",
    "nz_mpi_list": r"/recalled-food-products/[a-z0-9-]{8,}",
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
    links = list(dict.fromkeys(re.findall(pat, f.read_text())))[:2]
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
