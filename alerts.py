#!/usr/bin/env python3
"""Send recall alerts. Runs in "Update recalls" after each crawl (every 6 hours).

1. Gets the active subscribers and their watch items from the alerts Worker (Cloudflare, /v1/export).
2. Takes the recalls first seen in the last ALERT_DAYS days (plus new UK DVSA vehicle recalls) and matches them
   against each subscriber's watch items with matching.py, in the subscriber's countries.
3. Sends one push per subscriber per run (several matches are batched into one message) through Firebase Cloud
   Messaging, then tells the Worker what was sent so nothing is sent twice. Quiet hours: matches wait for the next run.

Settings (GitHub secrets / variables):
  ALERTS_URL            the Worker address, e.g. https://recallatlas-alerts.<account>.workers.dev
  ALERTS_KEY            shared secret between this job and the Worker
  FCM_SERVICE_ACCOUNT   Firebase service-account JSON. Without it the job runs dry: it matches and reports counts,
                        sends nothing and marks nothing as sent.
The job never prints device tokens, e-mail addresses or watch items; the run summary shows counts only.
"""
import datetime as dt, json, os, urllib.error, urllib.request
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

import crawl
import matching as M

SITE = "https://recallatlas.org"
ALERT_DAYS = 2
EU = set(crawl.EU_NAMES) - {"XI"}
LABEL_TYPE = {"brand+type": "check your model", "accessory": "part made for this brand", "counterfeit": "fake products"}


# ---------------------------------------------------------------- Worker API
def api(method, path, body=None):
    req = urllib.request.Request(os.environ["ALERTS_URL"].rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"authorization": "Bearer " + os.environ["ALERTS_KEY"],
                                          "content-type": "application/json", "user-agent": "RecallAtlas-alerts/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def subscribers():
    out, after = [], ""
    while True:
        page = api("GET", f"/v1/export?after={after}")
        out += page["subscribers"]
        if not page.get("next"): return out
        after = page["next"]


# ---------------------------------------------------------------- what is new
def new_recalls(archive, today):
    since = (today - dt.timedelta(days=int(os.environ.get("ALERT_DAYS", ALERT_DAYS)))).isoformat()
    rows = [r for r in archive.values() if r.get("first_seen", "") != "backfill" and r.get("first_seen", "") >= since]
    dvsa = Path(__file__).parent / "data" / "vehicles" / "uk-dvsa.json"
    end = today.isoformat()   # a few DVSA rows carry future dates (typos); those are left out
    uk = [d for d in json.loads(dvsa.read_text()) if since <= d["date"] <= end] if dvsa.exists() else []
    return rows, uk


def in_countries(r, countries):
    if not countries: return True
    want = set(countries) | ({"XI"} if "GB" in countries else set())
    have = {r.get("country")} | set(r.get("countries") or [])
    return bool(want & have) or (r.get("country") == "EU" and bool(want & EU))


# ---------------------------------------------------------------- matching
def match(sub, rows, uk):
    """[(recall id, label, title, url)] for one subscriber."""
    hits = {}
    for r in rows:
        if r["id"] in sub["sent"] or not in_countries(r, sub["countries"]): continue
        for it in sub["items"]:
            label = None
            k = it["kind"]
            if k == "product":
                tier = M.match_item(r, it.get("brand", ""), it.get("type", ""), it.get("model") or None, it.get("barcode") or None)
                if tier in ("barcode", "model"):
                    name = " ".join(x for x in (it.get("brand"), it.get("model")) if x)
                    label = f"Matches your {name}" if name else f"Matches barcode {it.get('barcode')}" if tier == "barcode" else "Matches a watched item"
                elif tier:
                    label = f"{it.get('brand')} {it.get('type')}: {LABEL_TYPE[tier]}"
            elif k == "vehicle":
                tier = M.match_vehicle(r, it["make"], it["model"], it.get("year"))
                if tier: label = f"{it.get('year') or ''} {it['make']} {it['model']}".strip() + ("" if tier == "vehicle" else ": check your year")
            elif k == "category" and r.get("category") == it["category"]:
                label = "New recall in a category you follow"
            elif k == "allergen" and it["allergen"] in M.allergens(r):
                label = f"Undeclared {it['allergen']}"
            elif k == "child" and it["tag"] in M.child_tags(r):
                label = "Children's product recall"
            if label:
                hits.setdefault(r["id"], (r["id"], label, r["title"], f"{SITE}/recall/{r['slug']}/"))
                break
    if not sub["countries"] or "GB" in sub["countries"]:
        for d in uk:
            rid = f"dvsa-{d['id']}"
            if rid in sub["sent"]: continue
            for it in sub["items"]:
                if it["kind"] == "vehicle" and (tier := M.match_uk_vehicle(d, it["make"], it["model"], it.get("year"))):
                    label = f"{it.get('year') or ''} {it['make']} {it['model']}".strip() + ("" if tier == "vehicle" else ": check your year")
                    hits.setdefault(rid, (rid, label, f"{d['make']} recall: {d['concern']}".title()[:120],
                                          "https://www.check-vehicle-recalls.service.gov.uk/"))
                    break
    return list(hits.values())


def quiet_now(sub, now):
    q = sub.get("quiet") or []
    if len(q) != 2: return False
    try:
        h = now.astimezone(ZoneInfo(sub.get("tz") or "UTC")).hour
    except Exception:
        h = now.hour
    a, b = q
    return a <= h < b if a < b else (h >= a or h < b)


def message(hits):
    if len(hits) == 1:
        rid, label, title, url = hits[0]
        return {"title": label, "body": title[:180] + " · Check the official notice before acting.", "url": url}
    return {"title": f"{len(hits)} new recalls match your watchlist",
            "body": "; ".join(h[1] for h in hits[:4])[:180] + (" …" if len(hits) > 4 else ""),
            "url": f"{SITE}/"}


# ---------------------------------------------------------------- Firebase Cloud Messaging (HTTP v1)
class FCM:
    def __init__(self, info):
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        self.project = info["project_id"]
        self.creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
        self.creds.refresh(Request())

    def send(self, token, msg):
        body = {"message": {"token": token, "notification": {"title": msg["title"], "body": msg["body"]},
                            "data": {"url": msg["url"]}}}
        req = urllib.request.Request(f"https://fcm.googleapis.com/v1/projects/{self.project}/messages:send",
                                     data=json.dumps(body).encode(), method="POST",
                                     headers={"authorization": f"Bearer {self.creds.token}", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30):
                return "sent"
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            return "invalid" if e.code == 404 or "UNREGISTERED" in detail or "INVALID_ARGUMENT" in detail else f"error {e.code}"


# ---------------------------------------------------------------- main
def main():
    if not os.environ.get("ALERTS_URL") or not os.environ.get("ALERTS_KEY"):
        print("alerts: ALERTS_URL / ALERTS_KEY not set, nothing to do"); return
    now = dt.datetime.now(dt.timezone.utc)
    archive = crawl.load_archive(); crawl.apply_enrich(archive)
    rows, uk = new_recalls(archive, now.date())
    subs = subscribers()
    fcm = FCM(json.loads(os.environ["FCM_SERVICE_ACCOUNT"])) if os.environ.get("FCM_SERVICE_ACCOUNT") else None
    stats, sent_pairs, invalid = Counter(), [], []
    for sub in subs:
        hits = match(sub, rows, uk)
        if not hits: continue
        stats["subscribers with matches"] += 1
        stats["matches"] += len(hits)
        if quiet_now(sub, now):
            stats["held for quiet hours"] += 1; continue
        if sub["channel"] != "push":
            stats["e-mail (not sent yet: e-mail service not set up)"] += 1; continue
        if not fcm:
            stats["would send (dry run)"] += 1; continue
        result = fcm.send(sub["address"], message(hits))
        stats[f"push {result}"] += 1
        if result == "sent": sent_pairs += [(sub["id"], h[0]) for h in hits]
        elif result == "invalid": invalid.append(sub["id"])
    if sent_pairs: api("POST", "/v1/sent", {"pairs": sent_pairs})
    if invalid: api("POST", "/v1/invalid", {"ids": invalid})
    lines = [f"new recalls considered: {len(rows)} (+{len(uk)} UK vehicle)", f"active subscribers: {len(subs)}",
             "mode: " + ("live" if fcm else "dry run (no FCM_SERVICE_ACCOUNT)")] + [f"{k}: {v}" for k, v in stats.items()]
    print("alerts:\n  " + "\n  ".join(lines))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("## Alerts\n\n" + "\n".join(f"- {l}" for l in lines) + "\n")


if __name__ == "__main__":
    main()
