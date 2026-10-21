"""Picture cards for Instagram (1080x1350 JPEG), drawn at build time and published under /social/.

Instagram only takes posts with an image, and it fetches the image from a public URL, so build_site.py calls
write() after the pages are built: the cards then go live with the deploy, before social.py posts them.
Cards are drawn for
  - every recall flagged serious and first seen in the last CARD_DAYS days (social.py posts those from the last 2),
  - the latest finished week (the weekly roundup),
  - each app promo in APP_PROMOS (only while build_site.APP_LIVE is True).
Fonts are the site's own (assets/fonts, SIL OFL), colours as in template.html. Nothing is fetched.
Paths: /social/recall-<slug>.jpg, /social/weekly-<YYYY-wNN>.jpg, /social/app-<n>.jpg (see card_path()).
"""
import datetime as dt
import re
from collections import Counter
from pathlib import Path

CARD_DAYS = 3
W, H = 1080, 1350
BG, SURF, INK, MUTED, LINE = "#f2f4f6", "#ffffff", "#15212c", "#5b6875", "#dde2e7"
ACC, ACC_SOFT = "#b8480f", "#fbe9dd"

# The app posts (Bluesky, Mastodon, Facebook, Instagram), one a day, rotating. social.py imports these.
APP_PROMOS = [
    "Is anything you own recalled? The Recall Atlas app for Android watches official recalls from 36 countries "
    "and alerts you when one matches your things.",
    "Car seats, smoke alarms and helmets expire. Recall Atlas for Android reminds you before they need replacing, and "
    "alerts you if they are recalled.",
    "Food allergy at home? Recall Atlas sends an alert when a food is recalled for an undeclared allergen you "
    "chose: peanut, milk, egg, sesame and more. Android app.",
    "Add your car's make, model and year and Recall Atlas alerts you to new recalls for it (US, Canada and UK). "
    "Android app.",
    "Recall Atlas for Android: official recalls from 36 countries in one calm feed, readable offline, each with what "
    "to do and a link to the official notice.",
    "No ads, no tracking. The Recall Atlas app keeps your list on your phone and only alerts you when "
    "an official recall matches it.",
    "Safety alerts are always free in Recall Atlas. Pro adds more things, more countries and barcode scanning. "
    "Get it on Google Play.",
]
# Short headline per promo for the picture (the full text goes in the caption).
APP_HEADLINES = [
    "Is anything you own recalled?",
    "Car seats and smoke alarms expire",
    "Food allergy at home?",
    "Is your car under a recall?",
    "Official recalls from 36 countries",
    "No ads. No tracking.",
    "Safety alerts are always free",
]


def card_path(kind, key):
    """Site path of a card. kind: recall (key = slug), weekly (key = YYYY-wNN), app (key = promo index)."""
    return f"/social/{kind}-{key}.jpg"


# ---------- drawing ----------
def _fonts(root):
    from PIL import ImageFont
    d = Path(root) / "assets" / "fonts"
    cache = {}

    def F(kind, size, wght=None):
        k = (kind, size, wght)
        if k not in cache:
            if kind == "head":
                f = ImageFont.truetype(str(d / "archivo-latin-wdth-normal.woff2"), size)
                f.set_variation_by_axes([wght or 800, 100])
            elif kind == "mono":
                f = ImageFont.truetype(str(d / "ibm-plex-mono-latin-500-normal.woff2"), size)
            else:
                f = ImageFont.truetype(str(d / "public-sans-latin-wght-normal.woff2"), size)
                f.set_variation_by_axes([wght or 400])
            cache[k] = f
        return cache[k]
    return F


def _wrap(d, text, font, width):
    lines, cur = [], ""
    for w in (text or "").split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= width or not cur: cur = t
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines


def _block(d, xy, text, font, width, fill, max_lines, lh=1.25):
    """Wrapped text, cut with an ellipsis after max_lines. Returns the y below it."""
    x, y = xy
    lines = _wrap(d, text, font, width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and d.textlength(last + "…", font=font) > width: last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        lines[-1] = last.rstrip(",.;:–-") + "…"
    for ln in lines:
        d.text((x, y), ln, font=font, fill=fill); y += int(font.size * lh)
    return y


def _fit(d, text, F, width, max_lines, sizes):
    """Largest headline size whose text fits in max_lines."""
    for s in sizes:
        if len(_wrap(d, text, F("head", s), width)) <= max_lines: return s
    return sizes[-1]


def _mark(size, fill=ACC, inner="#ffffff"):
    from PIL import Image, ImageDraw
    S = 8; im = Image.new("RGBA", (64 * S, 64 * S), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.ellipse([11 * S, 3.6 * S, 53 * S, 45.6 * S], fill=fill)
    d.polygon([(13.5 * S, 33 * S), (32 * S, 60 * S), (50.5 * S, 33 * S)], fill=fill)
    d.rounded_rectangle([28.5 * S, 13 * S, 35.5 * S, 30 * S], radius=3.5 * S, fill=inner)
    d.ellipse([28 * S, 33.5 * S, 36 * S, 41.5 * S], fill=inner)
    return im.resize((size, size), Image.LANCZOS)


def _chip(d, x, y, text, F, fg, bg):
    f = F("body", 28, 650)
    w = d.textlength(text, font=f) + 36
    d.rounded_rectangle([x, y, x + w, y + 52], radius=12, fill=bg)
    d.text((x + 18, y + 26), text, font=f, fill=fg, anchor="lm")
    return x + w + 12


def _header(im, d, F, label):
    im.alpha_composite(_mark(64), (64, 60))
    d.text((142, 92), "Recall Atlas", font=F("head", 40, 800), fill=INK, anchor="lm")
    d.text((W - 64, 92), label, font=F("mono", 26), fill=MUTED, anchor="rm")


def _footer(d, F, line):
    d.rectangle([0, H - 150, W, H], fill=INK)
    d.text((64, H - 102), line, font=F("body", 32, 650), fill="#ffffff", anchor="lm")
    d.text((64, H - 52), "Unofficial. Always check the official notice before acting.", font=F("body", 26), fill="#c9d2db", anchor="lm")


def _save(im, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(path, "JPEG", quality=88, optimize=True, progressive=False)


def clean_title(r, B):
    """The site's cleaned search title ('Product recall (Brand)'), without the month: the card shows the date."""
    t = B.seo_title(r, 140)
    return re.sub(r" \((?:(.+?), )?[A-Z][a-z]{2} \d{4}\)$", lambda m: f" ({m.group(1)})" if m.group(1) else "", t)


def recall_card(r, B, F):
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (W, H), BG); d = ImageDraw.Draw(im)
    _header(im, d, F, "SERIOUS RECALL")
    x = _chip(d, 64, 170, B.CATS.get(r.get("category"), "Other"), F, ACC, ACC_SOFT)
    _chip(d, x, 170, B.NAMES.get(r["country"], r["country"]), F, INK, "#e6eaee")
    title = clean_title(r, B)
    size = _fit(d, title, F, W - 128, 5, [92, 84, 76, 68, 60, 54])
    y = _block(d, (64, 270), title, F("head", size), W - 128, INK, 5, 1.08) + 40
    if r.get("hazard"):
        hf, lh = F("body", 40), 54
        box_top = y
        hz_lines = min(8, max(1, len(_wrap(d, r["hazard"], hf, W - 192))))
        box_h = 104 + hz_lines * lh
        if box_top + box_h > H - 290: hz_lines = max(1, (H - 290 - box_top - 104) // lh); box_h = 104 + hz_lines * lh
        d.rounded_rectangle([64, box_top, W - 64, box_top + box_h], radius=24, fill=SURF, outline=LINE, width=2)
        d.text((96, box_top + 32), "HAZARD", font=F("mono", 26), fill=MUTED)
        _block(d, (96, box_top + 76), r["hazard"], hf, W - 192, INK, hz_lines, lh / 40)
    day = dt.date.fromisoformat(r["date"])
    src = B.AGENCY.get(r.get("feed"), r["source"])
    src = src[4:] if src.startswith("the ") else src
    _block(d, (64, H - 250), f"Source: {src} · {B.fmt_day(day)}", F("body", 30, 500), W - 128, MUTED, 2, 1.3)
    _footer(d, F, "Details and the official notice: recallatlas.org")
    return im


def weekly_card(key, rows, prev, B, F):
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (W, H), BG); d = ImageDraw.Draw(im)
    _header(im, d, F, "WEEKLY ROUNDUP")
    d.text((64, 200), B.week_label(key), font=F("head", 56, 800), fill=INK)
    d.text((64, 300), f"{len(rows):,}", font=F("head", 200, 900), fill=ACC)
    sub = "official recalls and safety alerts"
    if prev:
        ch = round((len(rows) - len(prev)) / len(prev) * 100)
        if ch: sub += f", {'up' if ch > 0 else 'down'} {abs(ch)}% on the week before"
    _block(d, (64, 530), sub, F("body", 34, 500), W - 128, MUTED, 2)
    cats = Counter(r["category"] for r in rows).most_common(4)
    top = cats[0][1] if cats else 1
    y = 630
    for c, n in cats:
        d.text((64, y), B.CATS.get(c, "Other"), font=F("body", 30, 600), fill=INK)
        d.text((W - 64, y), str(n), font=F("mono", 30), fill=INK, anchor="ra")
        d.rounded_rectangle([64, y + 46, 64 + max(12, int((W - 128) * n / top)), y + 64], radius=9, fill=ACC)
        y += 84
    ser = B.serious(rows, 3)
    if ser:
        d.text((64, y + 6), f"FLAGGED SERIOUS ({len(B.serious(rows, 10 ** 6))})", font=F("mono", 24), fill=MUTED)
        y += 46
        for r in ser:
            if y > H - 200: break
            r = dict(r, title=clean_title(r, B))
            y = _block(d, (64, y), "• " + r["title"], F("body", 28, 500), W - 128, INK, 1, 1.2) + 10
    _footer(d, F, "Full roundup: recallatlas.org/weekly")
    return im


def app_card(i, F, root):
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (W, H), ACC); d = ImageDraw.Draw(im)
    im.alpha_composite(_mark(150, fill="#ffffff", inner=ACC), ((W - 150) // 2, 170))
    head = APP_HEADLINES[i]
    size = _fit(d, head, F, W - 160, 3, [96, 86, 76, 68])
    lines = _wrap(d, head, F("head", size), W - 160)
    y = 400
    for ln in lines:
        d.text((W / 2, y), ln, font=F("head", size), fill="#ffffff", anchor="ma"); y += int(size * 1.08)
    y += 30
    for ln in _wrap(d, "Recall alerts for what you own. Official sources, 36 countries.", F("body", 38, 500), W - 200):
        d.text((W / 2, y), ln, font=F("body", 38, 500), fill="#ffffff", anchor="ma"); y += 50
    badge_p = Path(root) / "assets" / "app" / "google-play-badge.webp"
    if badge_p.exists():
        b = Image.open(badge_p).convert("RGBA")
        b = b.resize((int(b.width * 120 / b.height), 120), Image.LANCZOS)
        im.alpha_composite(b, ((W - b.width) // 2, max(y + 50, 900)))
    d.text((W / 2, H - 200), "recallatlas.org/app", font=F("body", 40, 650), fill="#ffffff", anchor="mm")
    d.text((W / 2, H - 130), "Unofficial app, not a government service.", font=F("body", 30), fill="#ffe8da", anchor="mm")
    return im


# ---------- entry point ----------
def write(out, B, today=None):
    """Draws the cards into out/social/. B is the build_site module. Never fails the build."""
    try:
        from PIL import Image  # noqa: F401
        F = _fonts(B.ROOT)
        F("head", 40)
    except Exception as e:
        print(f"social cards: skipped ({e})")
        return 0
    today = today or dt.datetime.now(dt.timezone.utc).date()
    since = (today - dt.timedelta(days=CARD_DAYS)).isoformat()
    n = 0
    for r in B.ARCH:
        fs = r.get("first_seen") or ""
        if len(fs) == 10 and fs >= since and r.get("slug") and \
                B.sev_class((r.get("severity") or "") + " " + (r.get("hazard") or "")) == "high":
            try:
                _save(recall_card(r, B, F), Path(out) / card_path("recall", r["slug"]).lstrip("/")); n += 1
            except Exception as e:
                print(f"social cards: recall {r.get('id')} failed ({e})")
    weeks = B.week_groups(B.ARCH, today.isoformat())
    done = [k for k in weeks if k < B.week_key(today.isoformat())]
    if done:
        k = done[-1]
        _save(weekly_card(k, weeks[k], weeks.get(done[-2]) if len(done) > 1 else None, B, F),
              Path(out) / card_path("weekly", k).lstrip("/")); n += 1
    if getattr(B, "APP_LIVE", False):
        for i in range(len(APP_PROMOS)):
            _save(app_card(i, F, B.ROOT), Path(out) / card_path("app", i).lstrip("/")); n += 1
    print(f"social cards: {n} written")
    return n
