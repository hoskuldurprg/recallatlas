// Recall Atlas alerts back end (Cloudflare Worker + D1). Deployed by .github/workflows/alerts-deploy.yml.
//
// Kept small on purpose (free plan: 10 ms CPU per request). It only stores who watches what and hands that list to
// the GitHub job (alerts.py), which does the matching with matching.py and sends the pushes. It also fetches the
// two official feeds that block GitHub's servers (Australia's ACCC, USDA FSIS) for the crawler.
//
// App / website API (the caller keeps the secret it gets when subscribing; we store only its SHA-256):
//   POST   /v1/subscribers            {channel, address, platform, countries, tz, quiet, items} -> {id, secret}
//   GET    /v1/subscribers/:id        Authorization: Bearer <secret>  -> settings and items
//   PUT    /v1/subscribers/:id        same body as POST (replaces settings and items)
//   DELETE /v1/subscribers/:id        removes the subscriber and everything stored about it
// GitHub job API (Authorization: Bearer <ALERTS_KEY>, a Worker secret):
//   GET    /v1/export?after=<id>      active subscribers with items and recall ids sent in the last 14 days, 200 per page
//   POST   /v1/sent                   {pairs: [[subscriber_id, recall_id], ...]}
//   POST   /v1/invalid                {ids: [...]}  deactivate subscribers whose device token no longer works
//   GET    /v1/feed?src=accc|usda     the official feed, fetched from Cloudflare
//   GET    /v1/health

const FEEDS = {
  accc: "https://www.productsafety.gov.au/rss/feed.xml/psa_recall",
  usda: "https://www.fsis.usda.gov/fsis/api/recall/v/1",
};
const CATEGORIES = ["food", "kids", "electrical", "home", "sports", "tools", "vehicles", "medical", "cosmetics", "apparel", "other"];
const ALLERGENS = ["peanut", "tree nuts", "milk", "egg", "gluten", "sesame", "soy", "fish", "shellfish", "mustard", "celery", "lupin", "sulphites"];
const CHILD_TAGS = ["child", "car-seat", "sleep", "stroller", "button-battery", "magnets", "small-parts", "strangulation"];
const MAX_ITEMS = 100;
const ORIGINS = ["https://recallatlas.org", "https://www.recallatlas.org"];

const str = (v, max) => (typeof v === "string" ? v.trim().slice(0, max) : "");

function item(raw) {
  const kind = raw && raw.kind;
  if (kind === "product") {
    const d = { brand: str(raw.brand, 80), type: str(raw.type, 40), model: str(raw.model, 60) };
    const bc = str(raw.barcode, 20).replace(/[\s-]/g, "");
    if (/^\d{8}$|^\d{12,14}$/.test(bc)) d.barcode = bc;
    return d.brand || d.model || d.barcode ? { kind, d } : null;
  }
  if (kind === "vehicle") {
    const y = parseInt(raw.year, 10);
    const d = { make: str(raw.make, 40), model: str(raw.model, 60), year: y >= 1950 && y <= 2100 ? y : null };
    return d.make && d.model ? { kind, d } : null;
  }
  if (kind === "category") return CATEGORIES.includes(raw.category) ? { kind, d: { category: raw.category } } : null;
  if (kind === "allergen") return ALLERGENS.includes(raw.allergen) ? { kind, d: { allergen: raw.allergen } } : null;
  if (kind === "child") return CHILD_TAGS.includes(raw.tag) ? { kind, d: { tag: raw.tag } } : null;
  if (kind === "digest") return { kind, d: {} };   // weekly summary push turned on (alerts.py)
  return null;
}

function settings(body) {
  const channel = body.channel === "email" ? "email" : body.channel === "push" ? "push" : null;
  const address = str(body.address, 4096);
  if (!channel || !address) return { error: "channel ('push' or 'email') and address are required" };
  if (channel === "email" && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(address)) return { error: "invalid e-mail address" };
  const countries = Array.isArray(body.countries)
    ? [...new Set(body.countries.filter((c) => /^[A-Z]{2}$/.test(c)))].slice(0, 40) : [];
  const quiet = Array.isArray(body.quiet) && body.quiet.length === 2 && body.quiet.every((h) => Number.isInteger(h) && h >= 0 && h < 24)
    ? body.quiet : body.quiet && body.quiet.length === 0 ? [] : [22, 7];
  const items = (Array.isArray(body.items) ? body.items : []).map(item).filter(Boolean);
  if (items.length > MAX_ITEMS) return { error: `at most ${MAX_ITEMS} watch items` };
  return { channel, address, platform: str(body.platform, 10), countries, tz: str(body.tz, 40) || "UTC", quiet, items };
}

const json = (data, status = 200, extra = {}) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json", ...extra } });

async function sha256(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function token(bytes) {
  const a = new Uint8Array(bytes);
  crypto.getRandomValues(a);
  return [...a].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function same(a, b) {  // constant-time comparison of two strings
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let x = 0;
  for (let i = 0; i < a.length; i++) x |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return x === 0;
}

const bearer = (req) => (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");

async function readJson(req) {
  const text = await req.text();
  if (text.length > 64000) throw new Error("body too large");
  return JSON.parse(text || "{}");
}

async function saveItems(db, id, items) {
  const stmts = [db.prepare("DELETE FROM items WHERE subscriber_id = ?").bind(id)];
  items.forEach((it, i) => stmts.push(
    db.prepare("INSERT INTO items (subscriber_id, pos, kind, data) VALUES (?, ?, ?, ?)").bind(id, i, it.kind, JSON.stringify(it.d))));
  await db.batch(stmts);
}

async function owner(req, env, id) {
  const row = await env.DB.prepare("SELECT * FROM subscribers WHERE id = ?").bind(id).first();
  if (!row) return null;
  return same(await sha256(bearer(req)), row.secret_hash) ? row : false;
}

async function handle(req, env) {
  const url = new URL(req.url);
  const path = url.pathname.replace(/\/+$/, "");
  const now = new Date().toISOString();
  const m = path.match(/^\/v1\/subscribers\/([a-f0-9]{32})$/);

  if (path === "/v1/health") return json({ ok: true });

  if (path === "/v1/subscribers" && req.method === "POST") {
    const s = settings(await readJson(req));
    if (s.error) return json({ error: s.error }, 400);
    const exists = await env.DB.prepare("SELECT id FROM subscribers WHERE channel = ? AND address = ?").bind(s.channel, s.address).first();
    if (exists) return json({ error: "already subscribed; update it with its id and secret" }, 409);
    const id = token(16), secret = token(32);
    // E-mail subscriptions stay inactive until the address is confirmed (double opt-in, needs the e-mail service).
    await env.DB.prepare(`INSERT INTO subscribers (id, secret_hash, channel, address, platform, countries, tz, quiet, created, updated, active)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
      .bind(id, await sha256(secret), s.channel, s.address, s.platform, JSON.stringify(s.countries), s.tz,
            JSON.stringify(s.quiet), now, now, s.channel === "push" ? 1 : 0).run();
    await saveItems(env.DB, id, s.items);
    return json({ id, secret, items: s.items.length, active: s.channel === "push" }, 201);
  }

  if (m) {
    const row = await owner(req, env, m[1]);
    if (row === null) return json({ error: "not found" }, 404);
    if (row === false) return json({ error: "wrong secret" }, 403);
    if (req.method === "GET") {
      const { results } = await env.DB.prepare("SELECT kind, data FROM items WHERE subscriber_id = ? ORDER BY pos").bind(row.id).all();
      return json({ id: row.id, channel: row.channel, platform: row.platform, countries: JSON.parse(row.countries), tz: row.tz,
                    quiet: JSON.parse(row.quiet), tier: row.tier, active: !!row.active,
                    items: results.map((r) => ({ kind: r.kind, ...JSON.parse(r.data) })) });
    }
    if (req.method === "PUT") {
      const s = settings(await readJson(req));
      if (s.error) return json({ error: s.error }, 400);
      if (s.channel !== row.channel) return json({ error: "channel cannot change" }, 400);
      await env.DB.prepare("UPDATE subscribers SET address = ?, platform = ?, countries = ?, tz = ?, quiet = ?, updated = ?, active = ? WHERE id = ?")
        .bind(s.address, s.platform, JSON.stringify(s.countries), s.tz, JSON.stringify(s.quiet), now,
              row.channel === "push" ? 1 : row.active, row.id).run();
      await saveItems(env.DB, row.id, s.items);
      return json({ id: row.id, items: s.items.length });
    }
    if (req.method === "DELETE") {
      await env.DB.batch([
        env.DB.prepare("DELETE FROM items WHERE subscriber_id = ?").bind(row.id),
        env.DB.prepare("DELETE FROM sent WHERE subscriber_id = ?").bind(row.id),
        env.DB.prepare("DELETE FROM subscribers WHERE id = ?").bind(row.id)]);
      return json({ deleted: true });
    }
    return json({ error: "method not allowed" }, 405);
  }

  // ---- GitHub job only from here on
  if (!env.ALERTS_KEY || !same(bearer(req), env.ALERTS_KEY)) return json({ error: "not found" }, 404);

  if (path === "/v1/export" && req.method === "GET") {
    const after = url.searchParams.get("after") || "";
    const { results: subs } = await env.DB.prepare(
      "SELECT id, channel, address, platform, countries, tz, quiet, tier FROM subscribers WHERE active = 1 AND id > ? ORDER BY id LIMIT 200")
      .bind(after).all();
    if (!subs.length) return json({ subscribers: [], next: null });
    const ids = subs.map((s) => s.id), marks = ids.map(() => "?").join(",");
    const since = new Date(Date.now() - 14 * 864e5).toISOString();
    const [{ results: items }, { results: sent }] = await Promise.all([
      env.DB.prepare(`SELECT subscriber_id, kind, data FROM items WHERE subscriber_id IN (${marks}) ORDER BY pos`).bind(...ids).all(),
      env.DB.prepare(`SELECT subscriber_id, recall_id FROM sent WHERE subscriber_id IN (${marks}) AND at > ?`).bind(...ids, since).all()]);
    const by = Object.fromEntries(subs.map((s) => [s.id, { ...s, countries: JSON.parse(s.countries), quiet: JSON.parse(s.quiet), items: [], sent: [] }]));
    items.forEach((r) => by[r.subscriber_id].items.push({ kind: r.kind, ...JSON.parse(r.data) }));
    sent.forEach((r) => by[r.subscriber_id].sent.push(r.recall_id));
    return json({ subscribers: Object.values(by), next: subs.length === 200 ? ids[ids.length - 1] : null });
  }

  if (path === "/v1/sent" && req.method === "POST") {
    const pairs = ((await readJson(req)).pairs || []).filter((p) => Array.isArray(p) && p.length === 2).slice(0, 5000);
    const stmts = pairs.map(([s, r]) => env.DB.prepare("INSERT OR IGNORE INTO sent (subscriber_id, recall_id, at) VALUES (?, ?, ?)").bind(String(s), String(r), now));
    stmts.push(env.DB.prepare("DELETE FROM sent WHERE at < ?").bind(new Date(Date.now() - 30 * 864e5).toISOString()));
    for (let i = 0; i < stmts.length; i += 100) await env.DB.batch(stmts.slice(i, i + 100));
    return json({ saved: pairs.length });
  }

  if (path === "/v1/invalid" && req.method === "POST") {
    const ids = ((await readJson(req)).ids || []).map(String).slice(0, 1000);
    for (let i = 0; i < ids.length; i += 50) {
      const part = ids.slice(i, i + 50);
      await env.DB.prepare(`UPDATE subscribers SET active = 0, updated = ? WHERE id IN (${part.map(() => "?").join(",")})`).bind(now, ...part).run();
    }
    return json({ deactivated: ids.length });
  }

  if (path === "/v1/feed" && req.method === "GET") {
    const src = url.searchParams.get("src"), target = FEEDS[src];
    if (!target) return json({ error: "unknown feed" }, 400);
    let r;
    try {
      // Ordinary request headers (what a normal client sends), with our honest bot name in the user-agent.
      r = await fetch(target, { headers: {
        "user-agent": "Mozilla/5.0 (compatible; RecallAtlas/1.0; +https://recallatlas.org)",
        "accept": src === "usda" ? "application/json, text/plain, */*" : "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
        "accept-language": "en-AU,en-US;q=0.9,en;q=0.8",
        "accept-encoding": "gzip, deflate, br",
        "cache-control": "no-cache",
        "from": "info@recallatlas.org",
      } });
    } catch (e) {
      return json({ error: "feed unreachable", detail: String(e).slice(0, 200) }, 502);
    }
    return new Response(r.body, { status: r.status, headers: {
      "content-type": r.headers.get("content-type") || "text/plain",
      "x-origin-server": (r.headers.get("server") || "").slice(0, 60) } });
  }

  return json({ error: "not found" }, 404);
}

export default {
  async fetch(req, env) {
    const origin = req.headers.get("origin");
    const cors = ORIGINS.includes(origin) ? {
      "access-control-allow-origin": origin, "access-control-allow-methods": "GET, POST, PUT, DELETE",
      "access-control-allow-headers": "authorization, content-type", "vary": "origin" } : {};
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    let res;
    try {
      res = await handle(req, env);
    } catch (e) {
      res = json({ error: e instanceof SyntaxError ? "invalid JSON" : "server error" }, e instanceof SyntaxError ? 400 : 500);
    }
    for (const [k, v] of Object.entries(cors)) res.headers.set(k, v);
    return res;
  },
};
