#!/usr/bin/env python3
"""Posts to Bluesky, Mastodon and X after each deploy (run by the "Update recalls" workflow).

What is posted
  Bluesky + Mastodon: new recalls flagged serious (first seen in the last 2 days, max 3 per run), and the
                      weekly roundup once the week is over (from Monday 12:00 UTC).
  X:                  the weekly roundup only (the X API charges per post).
Every recall post names the agency that published it and links the official notice and the Recall Atlas page.
Texts are filled in from the official data with fixed sentences; nothing is AI-written.

Dry run
  A platform whose secrets are missing is not posted to; the posts it would have made are written to the
  Actions run summary and data/social/dry-run.log. Set SOCIAL_DRY_RUN=1 to dry-run everything.
  data/social/posted.json remembers what each platform has had (dry-run entries are marked), so nothing is
  posted twice and switching to live does not post a backlog.

Secrets (repo Settings -> Secrets and variables -> Actions)
  BSKY_HANDLE, BSKY_APP_PASSWORD               Bluesky handle and an app password (Settings -> App passwords)
  MASTODON_TOKEN [, MASTODON_INSTANCE]         access token with write:statuses; instance defaults to mastodon.social
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET   X app keys with Read and write permission
"""
import base64, hashlib, hmac, json, os, re, secrets, sys, time, urllib.parse, urllib.request
import datetime as dt
from pathlib import Path

sys.argv = sys.argv[:1]  # build_site reads sys.argv
import build_site as B

SITE = B.SITE
STATE = B.ROOT / "data" / "social" / "posted.json"
LOG = B.ROOT / "data" / "social" / "dry-run.log"
MAX_SERIOUS = 3
NOW = (dt.datetime.fromisoformat(os.environ["SOCIAL_NOW"]) if os.environ.get("SOCIAL_NOW")  # for testing
       else dt.datetime.now(dt.timezone.utc))
TAGS = {"food": "#FoodSafety", "kids": "#ChildSafety", "vehicles": "#CarRecall", "medical": "#DrugRecall",
        "electrical": "#ProductSafety", "home": "#ProductSafety", "sports": "#ProductSafety", "tools": "#ProductSafety",
        "cosmetics": "#ProductSafety", "apparel": "#ProductSafety", "other": "#ProductSafety"}


def env(*names):
    vals = [os.environ.get(n, "").strip() for n in names]
    return vals if all(vals) and os.environ.get("SOCIAL_DRY_RUN") != "1" else None


def cut(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n - 1].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def agency(r):
    return re.sub(r"^the ", "", B.AGENCY.get(r.get("feed"), r["source"]))


def where(r):
    return r.get("countryName") or B.NAMES.get(r["country"], r["country"])


# ---------- what to post ----------
def serious_items():
    since = (NOW.date() - dt.timedelta(days=2)).isoformat()
    rows = [r for r in B.ARCH if re.match(r"\d{4}-\d\d-\d\d$", r.get("first_seen") or "") and r["first_seen"] >= since
            and B.sev_class((r.get("severity") or "") + " " + (r.get("hazard") or "")) == "high"]
    rows.sort(key=lambda r: (r["first_seen"], r["date"], r["id"]), reverse=True)
    return [("recall:" + r["id"], r) for r in rows]


def weekly_item():
    """The last finished week, once it is Monday 12:00 UTC or later."""
    weeks = B.week_groups(B.ARCH, NOW.date().isoformat())
    cur = B.week_key(NOW.date().isoformat())
    done = [k for k in weeks if k < cur]
    if not done: return None
    k = done[-1]
    if NOW < dt.datetime.combine(B.week_range(k)[1] + dt.timedelta(days=1), dt.time(12), dt.timezone.utc): return None
    prev = weeks.get(done[-2]) if len(done) > 1 else None
    return ("weekly:" + k, {"key": k, "rows": weeks[k], "prev": prev})


# ---------- texts ----------
def recall_text(r, limit, url_len=None, links=True):
    """url_len: characters the platform counts per URL (Mastodon 23). links=False: no URLs in the text (Bluesky,
    where the recall page goes in the link card instead)."""
    page, notice = f"{SITE}/recall/{r['slug']}/", r["url"]
    tail = f"\n{where(r)} · Source: {agency(r)}"
    lk = f"\nOfficial notice: {notice}\nMore: {page}" if links else ""
    lk_len = (len("\nOfficial notice: \nMore: ") + 2 * url_len) if links and url_len else len(lk)
    tags = f"\n#Recall {TAGS.get(r['category'], '#ProductSafety')}"
    room = limit - len("Recall: ") - len(tail) - lk_len - len(tags) - 1
    title = cut(r["title"], min(140, room if not r.get("hazard") else max(60, room // 2)))
    left = room - len(title)
    hz = cut(r.get("hazard"), left) if r.get("hazard") and left > 30 else ""
    return f"Recall: {title}" + (f"\n{hz}" if hz else "") + tail + lk + tags


def weekly_text(w, limit, url_len=None, links=True):
    url = f"{SITE}/weekly/{w['key']}/"
    s = B.week_summary(w["key"], w["rows"], w["prev"], False)
    if limit < 400:  # short form for X and Bluesky
        rs, prev = w["rows"], w["prev"]
        ch = f", {'up' if len(rs) > len(prev) else 'down'} {abs(round((len(rs) - len(prev)) / len(prev) * 100))}% on the week before" \
            if prev and len(rs) != len(prev) else ""
        cats = " and ".join(B.CATS.get(c, "Other").lower() for c, _ in B.Counter(r["category"] for r in rs).most_common(2))
        hi = len(B.serious(rs, 10 ** 6))
        s = (f"{len(rs):,} official recalls in the US, Canada, the UK and Europe, {B.week_label(w['key'])}{ch}. "
             f"Most were {cats}; {hi} flagged as serious.")
    end = (f"\n{url}" if links else "") + " #Recall"
    room = limit - (1 + (url_len or len(url)) if links else 0) - len(" #Recall")
    return cut("Weekly recall roundup: " + s, room) + end


def counted(text, url_len=None):
    return len(re.sub(r"https?://\S+", "x" * url_len, text)) if url_len else len(text)


# ---------- platforms ----------
def http(method, url, body=None, headers=None, form=False):
    data = None
    if body is not None:
        data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={
        "User-Agent": "RecallAtlas/1.0 (+https://recallatlas.org)",
        **({"Content-Type": "application/x-www-form-urlencoded" if form else "application/json"} if data else {}),
        **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read() or b"{}")


class Bluesky:
    name, limit = "bluesky", 300

    def __init__(self, handle, password):
        s = http("POST", "https://bsky.social/xrpc/com.atproto.server.createSession", {"identifier": handle, "password": password})
        self.did, self.auth = s["did"], {"Authorization": "Bearer " + s["accessJwt"]}

    @staticmethod
    def text(kind, item):
        return recall_text(item, 300, links=False) if kind == "recall" else weekly_text(item, 300, links=False)

    def post(self, text, card):
        facets, b = [], text.encode()
        for m in re.finditer(rb"https?://[^\s]+", b):
            facets.append({"index": {"byteStart": m.start(), "byteEnd": m.end()},
                           "features": [{"$type": "app.bsky.richtext.facet#link", "uri": m.group().decode()}]})
        for m in re.finditer(rb"#(\w+)", b):
            facets.append({"index": {"byteStart": m.start(), "byteEnd": m.end()},
                           "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": m.group(1).decode()}]})
        rec = {"$type": "app.bsky.feed.post", "text": text, "createdAt": NOW.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
               "langs": ["en"], "facets": facets,
               "embed": {"$type": "app.bsky.embed.external", "external": card}}
        r = http("POST", "https://bsky.social/xrpc/com.atproto.repo.createRecord",
                 {"repo": self.did, "collection": "app.bsky.feed.post", "record": rec}, self.auth)
        return r.get("uri")


class Mastodon:
    name, limit = "mastodon", 500

    def __init__(self, token, instance=None):
        self.base = "https://" + (instance or "mastodon.social").replace("https://", "").strip("/")
        self.auth = {"Authorization": "Bearer " + token}

    @staticmethod
    def text(kind, item):
        return recall_text(item, 500, 23) if kind == "recall" else weekly_text(item, 500, 23)

    def post(self, text, card):
        r = http("POST", self.base + "/api/v1/statuses",
                 {"status": text, "visibility": os.environ.get("MASTODON_VISIBILITY", "unlisted"), "language": "en"},
                 {**self.auth, "Idempotency-Key": hashlib.sha1(text.encode()).hexdigest()}, form=True)
        return r.get("url")


class X:
    name, limit, weekly_only = "x", 280, True

    def __init__(self, key, secret, token, token_secret):
        self.k, self.s, self.t, self.ts = key, secret, token, token_secret

    @staticmethod
    def text(kind, item):
        return weekly_text(item, 280, 23)

    def post(self, text, card):
        url = "https://api.x.com/2/tweets"
        q = lambda v: urllib.parse.quote(str(v), safe="~")
        o = {"oauth_consumer_key": self.k, "oauth_nonce": secrets.token_hex(16), "oauth_signature_method": "HMAC-SHA1",
             "oauth_timestamp": str(int(time.time())), "oauth_token": self.t, "oauth_version": "1.0"}
        base = "&".join(["POST", q(url), q("&".join(f"{q(k)}={q(v)}" for k, v in sorted(o.items())))])
        o["oauth_signature"] = base64.b64encode(hmac.new(f"{q(self.s)}&{q(self.ts)}".encode(), base.encode(), hashlib.sha1).digest()).decode()
        auth = "OAuth " + ", ".join(f'{q(k)}="{q(v)}"' for k, v in sorted(o.items()))
        r = http("POST", url, {"text": text}, {"Authorization": auth})
        return "https://x.com/i/web/status/" + r.get("data", {}).get("id", "")


# ---------- run ----------
def main():
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    platforms = [
        ("bluesky", Bluesky, env("BSKY_HANDLE", "BSKY_APP_PASSWORD")),
        ("mastodon", Mastodon, env("MASTODON_TOKEN") and env("MASTODON_TOKEN") + [os.environ.get("MASTODON_INSTANCE")]),
        ("x", X, env("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")),
    ]
    items = [("recall", k, r) for k, r in serious_items()]
    w = weekly_item()
    if w: items.append(("weekly", w[0], w[1]))
    summary, log = ["## Social posts"], []
    for name, cls, creds in platforms:
        done = state.setdefault(name, {})
        live = None
        if creds:
            try: live = cls(*creds)
            except Exception as e: summary.append(f"- **{name}**: login failed ({e}); dry run this time")
        mode = "live" if live else "dry run"
        todo = [(kind, k, it) for kind, k, it in items if k not in done and not (getattr(cls, "weekly_only", False) and kind != "weekly")]
        recalls = [x for x in todo if x[0] == "recall"][:MAX_SERIOUS]
        todo = recalls + [x for x in todo if x[0] == "weekly"]
        summary.append(f"- **{name}** ({mode}): {len(todo)} post(s)")
        for kind, k, it in todo:
            text = cls.text(kind, it)
            if kind == "recall":
                card = {"uri": f"{SITE}/recall/{it['slug']}/", "title": cut(it["title"], 120),
                        "description": cut(f"{agency(it)} · {where(it)} · {it.get('hazard') or ''}", 280)}
            else:
                card = {"uri": f"{SITE}/weekly/{it['key']}/", "title": f"Recall roundup: {B.week_label(it['key'])}",
                        "description": cut(B.week_summary(it["key"], it["rows"], it["prev"], False), 280)}
            if live:
                try:
                    ref = live.post(text, card)
                    done[k] = {"at": NOW.isoformat(timespec="minutes"), "ref": ref}
                    summary.append(f"  - posted {k}: {ref}")
                    time.sleep(2)
                except Exception as e:
                    summary.append(f"  - FAILED {k}: {e}")
            else:
                done[k] = {"at": NOW.isoformat(timespec="minutes"), "dry_run": True}
                log.append(f"[{NOW:%Y-%m-%d %H:%M}Z] {name} {k}\n{text}\n")
                summary.append(f"\n```\n{text}\n```")
    # keep state small: forget entries older than 30 days
    cutoff = (NOW - dt.timedelta(days=30)).isoformat()
    for d in state.values():
        for k in [k for k, v in d.items() if v.get("at", "") < cutoff]: del d[k]
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    if log:
        with LOG.open("a") as f: f.write("\n".join(log) + "\n")
        lines = LOG.read_text().splitlines()[-3000:]
        LOG.write_text("\n".join(lines) + "\n")
    out = "\n".join(summary)
    print(out)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f: f.write(out + "\n")


if __name__ == "__main__":
    main()
