"""Hub pages and the product check (website Phase 3).

  /allergies/                 allergy hub: one page and RSS feed per allergen (undeclared allergens in food recalls)
  /allergies/<allergen>/      e.g. /allergies/peanut/ and /allergies/peanut/feed.xml
  /child-safety/              baby and child safety hub
  /child-safety/<topic>/      sleep, strollers, button batteries, cords (car seats, magnets and choking link to the
                              existing /recalls/<topic>/ pages so the same list isn't published twice)
  /check/                     "check your product": searches the whole archive by brand, product, model or barcode
  /data/check.json            the compact search index /check/ loads on the first search

Tags come from matching.py (allergens() and child_tags()), the same rules the app's alerts use. build_site.py calls
tag(ARCH) before rendering, then write(...) at the end of main().
"""
import json, re
import matching as M

MIN_PAGE = 5          # an allergen or topic needs this many recalls for its own page
LIST_MAX = 200        # newest recalls listed on a hub page

# (key in matching.ALLERGENS, url slug, name used in headings)
ALLERGY = [("peanut", "peanut", "Peanut"), ("tree nuts", "tree-nuts", "Tree nut"), ("milk", "milk", "Milk"),
           ("egg", "egg", "Egg"), ("gluten", "gluten", "Gluten and wheat"), ("sesame", "sesame", "Sesame"),
           ("soy", "soy", "Soy"), ("fish", "fish", "Fish"), ("shellfish", "shellfish", "Shellfish"),
           ("mustard", "mustard", "Mustard"), ("celery", "celery", "Celery"), ("lupin", "lupin", "Lupin"),
           ("sulphites", "sulphites", "Sulphite")]

ALLERGY_TODO = [
    "Compare the product name, pack size, batch or lot code and best-before date with the official notice.",
    "If it matches, don't eat it. Return it to the shop for a refund or throw it away, as the notice says.",
    "If someone with this allergy has eaten it and has symptoms, follow their allergy action plan. "
    "For signs of a severe reaction (difficulty breathing, swelling of the throat, collapse), use their "
    "adrenaline auto-injector if they have one and call emergency services.",
    "Products without an allergy warning can still be recalled for other reasons; check the notice for everything it covers.",
]

# (matching tag, url slug, heading, short name, intro, what to do). Tags whose page already exists as a topic list
# (car seats, magnets, choking) link there instead of getting a second page with the same recalls.
CHILD = [
    ("sleep", "sleep", "Baby sleep product recalls", "Cots, cribs, bassinets and baby sleep products",
     "Recalls of cots, cribs, bassinets, Moses baskets, travel cots, baby sleeping bags and mattresses: products a baby "
     "sleeps in unsupervised, where a fault can mean suffocation, entrapment or a fall.",
     ["Check the brand, model and manufacture date on the label against the official notice.",
      "If it matches, stop using it for sleep straight away, even while you wait for a repair kit or refund.",
      "Whatever product you use, put a baby to sleep on their back, on a firm, flat mattress, with no pillows, "
      "bumpers or loose bedding (the advice of child-safety agencies in every country we cover).",
      "Second-hand cots and bassinets are often recalled models: check before you use one."]),
    ("stroller", "strollers", "Stroller and pram recalls", "Strollers, prams and pushchairs",
     "Recalls of strollers, prams, pushchairs and buggies: folding mechanisms that trap fingers, brakes that fail, "
     "parts a child can choke on, and frames that collapse.",
     ["Check the brand, model and production date (usually on a label on the frame) against the official notice.",
      "If it matches, stop using it until it is repaired or replaced as the notice describes.",
      "Many stroller recalls offer a free repair kit or part: register the product with the maker so you hear about the next one."]),
    ("button-battery", "button-batteries", "Button battery recalls", "Button and coin batteries",
     "Recalls of products where a child can get at a button or coin battery: remote controls, toys, scales, "
     "trackers and light-up items. A swallowed button battery can burn through the throat in about two hours.",
     ["Check the product against the official notice and keep it away from children until it is fixed or returned.",
      "Check that battery compartments in the house need a screwdriver or two actions to open.",
      "If you think a child has swallowed a button battery, go to the emergency department immediately, even if "
      "they seem fine. Don't make them vomit."]),
    ("strangulation", "cords-strangulation", "Cord and strangulation hazard recalls", "Cords, drawstrings and blind cords",
     "Recalls for strangulation risks: drawstrings on children's clothing, window blind cords, and cords or straps on "
     "toys and nursery products.",
     ["Check the product against the official notice.",
      "Remove drawstrings from children's hoods and necks, and keep blind cords tied up and out of reach.",
      "Keep cots and beds away from windows with corded blinds."]),
]
CHILD_LINKS = [("car-seat", "/recalls/car-seats/", "Car seat recalls"), ("magnets", "/recalls/magnets/", "Magnet recalls"),
               ("small-parts", "/recalls/choking-hazard/", "Choking hazard recalls"),
               (None, "/recalls/baby-products/", "All baby product recalls"), (None, "/recalls/toys-kids/", "All toy and children's product recalls")]


def tag(rows):
    """Adds _allergens and _child to each archive row (used by the hubs and the recall pages)."""
    for r in rows:
        r["_allergens"] = M.allergens(r)
        r["_child"] = M.child_tags(r)


def counts(B):
    a = {k: sum(1 for r in B.ARCH if k in r["_allergens"]) for k, _, _ in ALLERGY}
    c = {t: sum(1 for r in B.ARCH if t in r["_child"]) for t, *_ in CHILD}
    return a, c


def recall_links(r, B):
    """Short 'see also' line for a recall page: the allergen and child-safety hub pages this recall belongs to."""
    links = []
    for k, slug, name in ALLERGY:
        if k in r.get("_allergens", []) and B.HUB_COUNTS[0].get(k, 0) >= MIN_PAGE:
            links.append((f"/allergies/{slug}/", f"{name} allergy recalls"))
    for t, slug, h1, *_ in CHILD:
        if t in r.get("_child", []) and B.HUB_COUNTS[1].get(t, 0) >= MIN_PAGE:
            links.append((f"/child-safety/{slug}/", h1))
    if not links: return ""
    return ('<p class="hublinks">See also: ' + " · ".join(f'<a href="{p}">{B.esc(n)}</a>' for p, n in links) + "</p>")


# ---------------------------------------------------------------- pages
def _page(B, path, title, desc, crumbs, body, footer, feed=None):
    nav = " › ".join(f'<a href="{p}">{B.esc(n)}</a>' for n, p in crumbs)
    html = f"""<div class="wrap">
<header class="top slim">{B.TOPLINE}</header>
<nav class="crumbs" aria-label="Breadcrumb">{nav}</nav>
<article class="recall hub">
{body}
</article></div>
{footer}{B.CONSENT}"""
    return (B.head_html(title, desc, B.SITE + path, "website", crumbs, feeds=[feed] if feed else ())
            + html + "</body>\n</html>\n")


def _countries(B, rs, n=6):
    from collections import Counter
    c = Counter(r["country"] for r in rs).most_common(n)
    return "".join(f'<li><b>{B.flag(cc, "fl sm")}{B.esc(B.NAMES.get(cc, "EU-wide") if cc != "EU" else "EU-wide")}</b><span>{k}</span></li>' for cc, k in c)


def _stats(B, rs, since90):
    recent = sum(1 for r in rs if r["date"] >= since90)
    srcs = sorted({r["source"] for r in rs})
    return (f'<section class="ystats"><div><h4>Recalls</h4><div class="big">{len(rs)}</div><p class="note">since {B.esc(rs[-1]["date"][:7])}</p></div>'
            f'<div><h4>Last 90 days</h4><div class="big">{recent}</div><p class="note">newest {B.esc(rs[0]["date"])}</p></div>'
            f'<div><h4>Where</h4><ol>{_countries(B, rs)}</ol></div>'
            f'<div><h4>Sources</h4><p class="note">{B.esc(", ".join(srcs))}</p></div></section>')


def _app_line(B, what):
    if not getattr(B, "APP_LIVE", False): return ""
    return (f'<aside class="appbox"><p><b>Get an alert next time.</b> The Recall Atlas app for Android can alert you to '
            f'new {B.esc(what)} recalls in your country.</p>{B.play_badge("hub")}</aside>')


def allergen_page(B, k, slug, name, rs, others, footer, since90):
    path = f"/allergies/{slug}/"
    feed = (f"{path}feed.xml", f"Recall Atlas: {name.lower()} allergy recalls")
    title = f"{name} allergy recalls: undeclared {name.lower()} in food ({len(rs)}) | Recall Atlas"
    desc = (f"{len(rs)} official food recalls where {name.lower()} was in a product but not declared on the label, from "
            f"{B.COVERAGE}. Newest first, updated every 6 hours, with an RSS feed.")
    crumbs = [("Recall Atlas", "/"), ("Allergies", "/allergies/"), (f"{name} allergy", path)]
    other = " · ".join(f'<a href="/allergies/{s}/">{B.esc(n)}</a>' for s, n in others if s != slug)
    body = f"""<h1>{B.esc(name)} allergy recalls</h1>
<p class="lede">Official food recalls where {B.esc(name.lower())} was in the product but missing from the label, or the label was wrong, from food safety agencies in {B.esc(B.COVERAGE)}. Newest first.</p>
<p><a class="rss" href="{feed[0]}">RSS feed for {B.esc(name.lower())} recalls</a></p>
{_stats(B, rs, since90)}
<h2>What to do</h2>
<ol class="todo">{"".join(f"<li>{B.esc(x)}</li>" for x in ALLERGY_TODO)}</ol>
<p class="note">General guidance, not medical advice. The official notice has the exact products and batch codes and takes priority. Recalls are tagged automatically from the notice text, so one can be missing here if the notice doesn't name {B.esc(name.lower())}; your country's food agency remains the place to check.</p>
{_app_line(B, name.lower() + " allergy")}
<h2>Latest {B.esc(name.lower())} recalls</h2>
<ol class="list">{B.render_rows(rs[:LIST_MAX])}</ol>
{f'<p class="note">Showing the newest {LIST_MAX} of {len(rs)}.</p>' if len(rs) > LIST_MAX else ""}
<h2>Other allergens</h2>
<p class="hubnav">{other}</p>"""
    return path, feed, _page(B, path, title, desc, crumbs, body, footer, feed)


def allergy_index(B, items, footer, since90):
    path = "/allergies/"
    lis = "".join(f'<li><a href="/allergies/{s}/"><b>{B.esc(n)}</b></a><span>{len(rs)} recalls · {sum(1 for r in rs if r["date"] >= since90)} in the last 90 days</span></li>'
                  for k, s, n, rs in items)
    total = len({r["id"] for *_, rs in items for r in rs})
    body = f"""<h1>Food allergy recalls</h1>
<p class="lede">{total:,} official food recalls for undeclared allergens since 2021, from food safety agencies in {B.esc(B.COVERAGE)}. Pick an allergen for its recalls and its own RSS feed.</p>
<ul class="hubcards">{lis}</ul>
<h2>What to do if a recall matches</h2>
<ol class="todo">{"".join(f"<li>{B.esc(x)}</li>" for x in ALLERGY_TODO)}</ol>
<p class="note">General guidance, not medical advice. Recalls are tagged automatically from the official notice text. See also <a href="/recalls/food-allergens/">all allergen recalls in one list</a> and <a href="/recalls/food/">all food recalls</a>.</p>
{_app_line(B, "allergy")}"""
    return _page(B, path, f"Food allergy recalls by allergen ({total:,}) | Recall Atlas",
                 f"Undeclared peanut, milk, egg, gluten, sesame and other allergen recalls from {B.COVERAGE}, one page and RSS feed per allergen.",
                 [("Recall Atlas", "/"), ("Allergies", path)], body, footer)


def child_page(B, t, slug, h1, short, intro, todo, rs, footer, since90):
    path = f"/child-safety/{slug}/"
    feed = (f"{path}feed.xml", f"Recall Atlas: {h1.lower()}")
    crumbs = [("Recall Atlas", "/"), ("Child safety", "/child-safety/"), (short, path)]
    body = f"""<h1>{B.esc(h1)}</h1>
<p class="lede">{B.esc(intro)}</p>
<p><a class="rss" href="{feed[0]}">RSS feed</a></p>
{_stats(B, rs, since90)}
<h2>What to do</h2>
<ol class="todo">{"".join(f"<li>{B.esc(x)}</li>" for x in todo)}</ol>
<p class="note">General guidance. The official notice has the exact models and remedy and takes priority. Recalls are tagged automatically from the notice text.</p>
{_app_line(B, "children's product")}
<h2>Latest recalls</h2>
<ol class="list">{B.render_rows(rs[:LIST_MAX])}</ol>
{f'<p class="note">Showing the newest {LIST_MAX} of {len(rs)}.</p>' if len(rs) > LIST_MAX else ""}
<h2>More child safety</h2>
<p class="hubnav"><a href="/child-safety/">Child safety hub</a> · {" · ".join(f'<a href="{p}">{B.esc(n)}</a>' for _, p, n in CHILD_LINKS)}</p>"""
    return path, feed, _page(B, path, f"{h1} ({len(rs)}) | Recall Atlas",
                             f"{len(rs)} official recalls: {short.lower()}, from {B.COVERAGE}. What to do, newest first, RSS feed.",
                             crumbs, body, footer, feed)


def child_index(B, items, footer, since90):
    path = "/child-safety/"
    lis = "".join(f'<li><a href="/child-safety/{slug}/"><b>{B.esc(short)}</b></a><span>{len(rs)} recalls · {sum(1 for r in rs if r["date"] >= since90)} in the last 90 days</span></li>'
                  for t, slug, h1, short, rs in items)
    lis += "".join(f'<li><a href="{p}"><b>{B.esc(n)}</b></a><span>list by product type</span></li>' for _, p, n in CHILD_LINKS)
    body = f"""<h1>Baby and child safety recalls</h1>
<p class="lede">Recalls of the products that matter most for young children: car seats, cots and baby sleep products, strollers, and the hidden hazards (button batteries, magnets, small parts and cords), from {B.esc(B.COVERAGE)}.</p>
<ul class="hubcards">{lis}</ul>
<h2>Before you buy or accept second-hand</h2>
<ol class="todo"><li>Search the brand and model in <a href="/check/">Check a product</a>.</li><li>Look for the model number and manufacture date on the label, and keep a photo of it.</li><li>Register car seats, cots and strollers with the maker so you hear about recalls directly.</li></ol>
{_app_line(B, "children's product")}"""
    return _page(B, path, "Baby and child safety recalls | Recall Atlas",
                 f"Car seat, cot, stroller, button battery, magnet and choking-hazard recalls from {B.COVERAGE}, with what to do.",
                 [("Recall Atlas", "/"), ("Child safety", path)], body, footer)


def check_page(B, footer):
    path = "/check/"
    body = """<h1>Check a product</h1>
<p class="lede">Search every recall since 2021 by brand, product name, model number or barcode. Results link to the recall and its official notice.</p>
<form class="checkform" id="checkForm" role="search"><input id="checkQ" type="search" name="q" placeholder="e.g. Britax, iPhone charger, 5012345678900" autocomplete="off" aria-label="Brand, product, model or barcode"><button class="cta" type="submit">Check</button></form>
<p class="note" id="checkMsg">Tip: the model number and barcode are on the label or the box. Searching by model finds the exact recall faster than by product type.</p>
<ol class="list" id="checkResults"></ol>
<p class="note">No match doesn't mean a product is safe: some recalls name only the product type, and Recall Atlas only covers the agencies listed in the <a href="/disclaimer/">disclaimer</a>. Check the official recall site in your country and with the maker.</p>
<script>
(()=>{
const $=s=>document.querySelector(s), esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const norm=s=>String(s||"").normalize("NFKD").replace(/[\\u0300-\\u036f]/g,"").toLowerCase().replace(/[^a-z0-9]+/g," ").trim();
const squash=s=>norm(s).replace(/ /g,"");
const slugify=t=>String(t).normalize("NFKD").replace(/[^\\x00-\\x7f]/g,"").toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"").slice(0,70).replace(/-+$/,"")||"recall";
let IDX=null;
async function load(){ if(IDX) return IDX; $("#checkMsg").textContent="Loading the recall archive (about 2.5 MB, once)…";
  const d=await (await fetch("/data/check.json")).json();
  IDX=d.r.map(r=>({t:r[0],b:r[1],c:r[2],d:r[3],s:r[4],i:r[5]||"",p:r[6]||"",tx:" "+norm(r[0]+" "+r[1]+" "+(r[6]||""))+" ",cd:squash((r[5]||"")+" "+r[0])}));
  IDX.cats=d.cats; return IDX; }
function search(q){
  const toks=norm(q).split(" ").filter(t=>t.length>1), sq=squash(q), digits=q.replace(/\\D/g,"");
  if(!toks.length) return [];
  const bc=/^\\d{8,14}$/.test(q.replace(/[\\s-]/g,""));
  const out=[];
  for(const r of IDX){
    let score=0;
    if(bc){ if(r.cd.includes(digits)) score=10; else continue; }
    else{
      let ok=true;
      for(const t of toks){
        if(r.tx.includes(" "+t)){score+=1; continue;}
        if(/\\d/.test(t)&&t.length>2&&r.cd.includes(t)){score+=4; continue;}
        ok=false; break;
      }
      if(!ok) continue;
      if(sq.length>3&&/\\d/.test(sq)&&r.cd.includes(sq)) score+=5;
      if(r.b&&norm(r.b)===norm(q)) score+=2;
    }
    out.push([score,r]);
  }
  out.sort((a,b)=>b[0]-a[0]||(a[1].d<b[1].d?1:-1));
  return out.slice(0,100).map(x=>x[1]);
}
const flag=c=>`<img class="fl" src="/assets/flags/${c==="GB"||c==="XI"?"gb":c.toLowerCase()}.svg" alt="" width="22" height="16" loading="lazy" onerror="this.remove()">`;
async function run(q){
  q=q.trim(); if(!q) return;
  await load();
  history.replaceState(null,"","?q="+encodeURIComponent(q));
  const rs=search(q);
  $("#checkMsg").innerHTML=rs.length?`${rs.length===100?"100+":rs.length} recall${rs.length===1?" mentions":"s mention"} <b>${esc(q)}</b>. Open each one and compare the model, batch and dates with the official notice.`
    :`No match found in our data for <b>${esc(q)}</b>. That doesn't mean the product is safe: try the brand alone, the model number, or check the official recall site in your country.`;
  $("#checkResults").innerHTML=rs.map(r=>{const slug=r.s.includes("-")?r.s:slugify(r.t)+"-"+r.s;
    return `<li class="item"><div class="cc">${flag(r.c)}${r.c==="GB"?"UK":esc(r.c)}</div><div class="body"><h3><a href="/recall/${esc(slug)}/">${esc(r.t)}</a></h3><div class="src"><span>${esc(r.d)}</span>${r.b?`<span>${esc(r.b)}</span>`:""}</div></div></li>`}).join("");
}
$("#checkForm").addEventListener("submit",e=>{e.preventDefault();run($("#checkQ").value);});
const q0=new URLSearchParams(location.search).get("q"); if(q0){$("#checkQ").value=q0;run(q0);}
})();
</script>"""
    return _page(B, path, "Check a product for recalls: search by brand, model or barcode | Recall Atlas",
                 f"Search every official recall since 2021 from {B.COVERAGE} by brand, product name, model number or barcode.",
                 [("Recall Atlas", "/"), ("Check a product", path)], body, footer)


def check_index(B):
    """Compact index for /check/: [title, brand, country, date, slug or slug id, model/barcode/batch codes, product]."""
    out = []
    for r in B.ARCH:
        if not r.get("slug"): continue
        ts = B.crawl.slugify(r["title"])
        s = r["slug"][len(ts) + 1:] if r["slug"].startswith(ts + "-") and len(r["slug"]) == len(ts) + 7 else r["slug"]
        ids = r.get("ids") or {}
        codes = []
        for k in ("model", "barcode", "batch"):
            v = ids.get(k) or []
            codes += v if isinstance(v, list) else [v]
        code_s = " ".join(dict.fromkeys(str(c) for c in codes if c))[:160]
        prod = r.get("product") or ""
        if M.norm(prod) in M.norm(r["title"]): prod = ""
        row = [r["title"], r.get("brand") or "", r["country"], r["date"], s, code_s, prod[:100]]
        while row and row[-1] == "": row.pop()
        out.append(row)
    return {"v": 1, "count": len(out), "r": out}


def hub_feed(B, path, title, page, desc, rows):
    rows = sorted(rows, key=lambda r: (B.seen_date(r), r["date"], r["id"]), reverse=True)[:B.FEED_ITEMS]
    items = []
    for r in rows:
        u = f"{B.SITE}/recall/{r['slug']}/"
        ag = B.AGENCY.get(r.get("feed"), r["source"])
        body = ((f"<p>{B.esc(r['hazard'])}</p>" if r.get("hazard") else "")
                + f"<p>{B.esc(ag[:1].upper() + ag[1:])} · {B.esc(r.get('countryName') or r['country'])} · {B.esc(r['date'])}</p>"
                + f'<p><a href="{B.esc(r["url"])}">Official notice</a> · <a href="{u}">On Recall Atlas</a></p>')
        items.append(f"<item><title>{B.esc(r['title'])}</title><link>{u}</link><guid isPermaLink=\"true\">{u}</guid>"
                     f"<pubDate>{B.rfc822(B.seen_date(r))}</pubDate><description>{B.esc(body)}</description></item>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>\n'
            f"<title>{B.esc(title)}</title><link>{B.SITE}{page}</link>\n<description>{B.esc(desc)}</description>\n"
            f'<language>en</language><ttl>360</ttl><lastBuildDate>{B.email_date(B.data["updated"])}</lastBuildDate>\n'
            f'<atom:link href="{B.SITE}{path}" rel="self" type="application/rss+xml"/>\n'
            + "\n".join(items) + "\n</channel>\n</rss>\n")


def write(B, footer):
    """Writes the hubs, /check/ and the search index. Returns (sitemap urls, [(feed path, feed title)])."""
    import datetime as dt
    since90 = (dt.date.fromisoformat(B.data["updated"][:10]) - dt.timedelta(days=90)).isoformat()
    lastmod = B.data["updated"][:10]
    urls, feeds = [], []

    def save(path, text):
        f = B.OUT / path.strip("/")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)

    items = []
    for k, slug, name in ALLERGY:
        rs = [r for r in B.ARCH if k in r["_allergens"]]
        if len(rs) >= MIN_PAGE: items.append((k, slug, name, rs))
    others = [(s, n) for _, s, n, _ in items]
    for k, slug, name, rs in items:
        path, feed, html = allergen_page(B, k, slug, name, rs, others, footer, since90)
        B.write(path, html); urls.append((B.SITE + path, lastmod)); feeds.append(feed)
        save(feed[0], hub_feed(B, feed[0], feed[1], path,
                               f"Official food recalls for undeclared {name.lower()}, collected by Recall Atlas every 6 hours.", rs))
    B.write("/allergies/", allergy_index(B, items, footer, since90)); urls.append((B.SITE + "/allergies/", lastmod))

    citems = []
    for t, slug, h1, short, intro, todo in CHILD:
        rs = [r for r in B.ARCH if t in r["_child"]]
        if len(rs) < MIN_PAGE: continue
        path, feed, html = child_page(B, t, slug, h1, short, intro, todo, rs, footer, since90)
        B.write(path, html); urls.append((B.SITE + path, lastmod)); feeds.append(feed)
        save(feed[0], hub_feed(B, feed[0], feed[1], path, f"{h1}, collected by Recall Atlas every 6 hours.", rs))
        citems.append((t, slug, h1, short, rs))
    B.write("/child-safety/", child_index(B, citems, footer, since90)); urls.append((B.SITE + "/child-safety/", lastmod))

    B.write("/check/", check_page(B, footer)); urls.append((B.SITE + "/check/", lastmod))
    (B.OUT / "data").mkdir(exist_ok=True)
    (B.OUT / "data" / "check.json").write_text(json.dumps(check_index(B), ensure_ascii=False, separators=(",", ":")))
    print(f"hubs: {len(items)} allergen pages, {len(citems)} child-safety pages, /check/ index of {len(B.ARCH)} recalls")
    return urls, feeds
