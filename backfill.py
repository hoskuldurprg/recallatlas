#!/usr/bin/env python3
"""One-off history load: fetches older recalls from sources that keep history and adds them
to the permanent archive (data/archive). Run from the "Backfill archive" GitHub workflow.

  python backfill.py 1825       # last 5 years (default)

Each source runs separately; one failing does not stop the others. Safe to run again:
existing recalls keep their URL and first_seen date.
"""
import sys, time, datetime as dt
import crawl
from crawl import get, requests, UA

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 1825
SINCE = (dt.date.today() - dt.timedelta(days=DAYS)).isoformat()
FIRST_SEEN = "backfill"  # marks rows loaded from history (not "new" for alerts or IndexNow)


def fda(since):
    out, s = [], since.replace("-", "")
    today = dt.date.today().strftime("%Y%m%d")
    for ep, kind in [("food", "Food"), ("drug", "Drug"), ("device", "Device")]:
        skip = 0
        while skip < 25000:  # openFDA's paging limit
            url = (f"https://api.fda.gov/{ep}/enforcement.json?search=report_date:[{s}+TO+{today}]"
                   f"&sort=report_date:desc&limit=1000&skip={skip}")
            try:
                res = get(url).json().get("results", [])
            except Exception as e:
                print(f"  FDA {ep} stopped at {skip}: {e}", file=sys.stderr); break
            out += [crawl.norm_fda(r, kind) for r in res]
            if len(res) < 1000: break
            skip += 1000
            time.sleep(1)
    seen, dedup = set(), []
    for r in out:
        key = (r["brand"], r["hazard"][:80], r["date"])
        if key not in seen:
            seen.add(key); dedup.append(r)
    return dedup


def nhtsa(since):
    url = ("https://data.transportation.gov/resource/6axg-epim.json"
           f"?$where=report_received_date>='{since}'&$order=report_received_date DESC&$limit=50000")
    return [crawl.norm_nhtsa(r) for r in get(url).json()]


def opss(since):
    out, start = [], 0
    while True:
        url = ("https://www.gov.uk/api/search.json?filter_format=product_safety_alert_report_recall"
               f"&order=-public_timestamp&count=500&start={start}&fields=title,link,public_timestamp,description")
        res = get(url).json()["results"]
        rows = [r for r in res if r["public_timestamp"][:10] >= since]
        out += [crawl.norm_opss(r) for r in rows]
        if len(res) < 500 or len(rows) < len(res): break
        start += 500
        time.sleep(1)
    return out


def fsa(since):
    url = f"https://data.food.gov.uk/food-alerts/id?since={since}T00:00:00&_limit=5000"
    return [crawl.norm_fsa(r) for r in get(url).json()["items"]]


KNOWN = set()  # ids already in the archive; filled in main()


def eu(since):
    return crawl.crawl_eu(since, max_pages=6000, known=KNOWN)


def canada(since):
    return crawl.crawl_canada(since, archived=True)  # include recalls Canada has since archived


SOURCES = [("CPSC", crawl.crawl_cpsc), ("FDA", fda), ("NHTSA", nhtsa), ("UK OPSS", opss),
           ("UK FSA", fsa), ("Canada", canada), ("EU Safety Gate", eu)]


def main():
    archive = crawl.load_archive()
    before = len(archive)
    KNOWN.update(archive)
    only = sys.argv[2].split(",") if len(sys.argv) > 2 else None
    for name, fn in SOURCES:
        if only and name not in only:
            continue
        try:
            rows = fn(SINCE)
            for r in rows: r["feed"] = name
            new = crawl.merge(archive, rows, FIRST_SEEN)
            print(f"{name}: {len(rows)} fetched, {new} new")
        except Exception as e:
            print(f"{name}: FAILED {e}", file=sys.stderr)
        crawl.save_archive(archive)  # save after each source so a timeout keeps what was done
    print(f"archive: {before} -> {len(archive)} recalls since {SINCE}")


if __name__ == "__main__":
    main()
