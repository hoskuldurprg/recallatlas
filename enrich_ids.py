#!/usr/bin/env python3
"""Catch-up for product identifiers on recalls archived before the crawler kept them (10 Oct 2026).

Reads the official notice of each archived recall that has no identifiers yet, newest first, and stores what it
finds in data/enrich/<source>.json ({recall id: {"ids": ..., "vehicles": ..., "counterfeit": ...}}; an empty
object means "checked, nothing found"). The crawler merges these files into the archive on its next run, so this
job never writes the archive itself and can run beside "Update recalls".

Usage: python enrich_ids.py [minutes] [source,source]   (defaults: 100 minutes, all sources below)
Prints "remaining=N progress=M" at the end (M = notices read successfully); the workflow starts itself again
while N > 0 and M > 0, so it stops by itself when everything is read or a source keeps failing.
"""
import json, re, sys, time
from pathlib import Path
import crawl as C

DIR = Path(__file__).parent / "data" / "enrich"
SAVE_EVERY = 200


def eu(r):
    nid = re.search(r"alertDetail/(\d+)", r.get("url", ""))
    if not nid: return {}
    d = C.get(f"{C.EU_API}{nid.group(1)}?language=en").json()
    return C.opt(ids=C.eu_ids(d), counterfeit=C.eu_counterfeit(d.get("product") or {}))


def opss(r):
    body = (C.get(r["url"].replace("https://www.gov.uk/", "https://www.gov.uk/api/content/")).json()
            .get("details") or {}).get("body") or ""
    return C.opt(ids=C.page_ids(body))


def page_with_vehicles(r):
    html = C.page(r["url"])
    extra = C.opt(ids=C.page_ids(html))
    if r.get("category") == "vehicles":
        extra.update(C.opt(vehicles=C.vehicle_lines(C.text_of(html))))
    return extra


def plain_page(r):
    return C.opt(ids=C.page_ids(C.page(r["url"])))


# Smaller sources first; EU Safety Gate (~17,000 notices, several runs) last.
FETCH = {"UK OPSS": (opss, 0.3), "Canada": (page_with_vehicles, 0.5), "NZ Product Safety": (plain_page, 0.5),
         "EU Safety Gate": (eu, 0.3)}


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main():
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else 100
    wanted = [s.strip() for s in sys.argv[2].split(",")] if len(sys.argv) > 2 and sys.argv[2].strip() else list(FETCH)
    deadline = time.time() + minutes * 60
    archive = C.load_archive()
    DIR.mkdir(parents=True, exist_ok=True)
    remaining = done_total = 0
    for name in wanted:
        fetch, pause = FETCH[name]
        path = DIR / f"{slug(name)}.json"
        store = json.loads(path.read_text()) if path.exists() else {}
        todo = sorted((r for r in archive.values() if r.get("feed") == name and not r.get("ids")
                       and r["id"] not in store), key=lambda r: r["date"], reverse=True)
        done = ok = found = fails = 0
        for r in todo:
            if time.time() > deadline: break
            try:
                store[r["id"]] = fetch(r)
                found += bool(store[r["id"]])
                ok += 1
                fails = 0
            except Exception as e:
                fails += 1
                print(f"  {r['id']}: {e}", file=sys.stderr)
                if fails >= 20:
                    print(f"{name}: 20 failures in a row, stopping this source", file=sys.stderr); break
            done += 1
            if done % SAVE_EVERY == 0:
                path.write_text(json.dumps(store, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                print(f"  {name}: {done} read, {found} with identifiers", flush=True)
            time.sleep(pause)
        path.write_text(json.dumps(store, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        left = sum(1 for r in todo if r["id"] not in store)
        remaining += left
        done_total += ok
        print(f"{name}: read {ok} ({done - ok} failed), {found} with identifiers, {left} left", flush=True)
    print(f"remaining={remaining} progress={done_total}")
    Path("enrich-status.txt").write_text(f"remaining={remaining}\nprogress={done_total}\n")


if __name__ == "__main__":
    main()
