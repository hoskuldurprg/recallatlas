-- Recall Atlas alerts database (Cloudflare D1). Safe to run again: everything is "IF NOT EXISTS".
-- Holds no names. A subscriber is a device token (app push) or an e-mail address (website alerts) plus what it watches.

CREATE TABLE IF NOT EXISTS subscribers (
  id          TEXT PRIMARY KEY,            -- random id given to the app / browser
  secret_hash TEXT NOT NULL,               -- SHA-256 of the secret only the app / browser holds
  channel     TEXT NOT NULL,               -- 'push' | 'email'
  address     TEXT NOT NULL,               -- FCM device token or e-mail address
  platform    TEXT NOT NULL DEFAULT '',    -- 'ios' | 'android' | 'web'
  countries   TEXT NOT NULL DEFAULT '[]',  -- JSON list of country codes, e.g. ["GB"]
  tz          TEXT NOT NULL DEFAULT 'UTC', -- IANA time zone, for quiet hours
  quiet       TEXT NOT NULL DEFAULT '[22,7]', -- JSON [from_hour, to_hour] local time; [] = no quiet hours
  tier        TEXT NOT NULL DEFAULT 'free',
  created     TEXT NOT NULL,
  updated     TEXT NOT NULL,
  active      INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS subscribers_address ON subscribers (channel, address);

CREATE TABLE IF NOT EXISTS items (
  subscriber_id TEXT NOT NULL,
  pos           INTEGER NOT NULL,
  kind          TEXT NOT NULL,   -- 'product' | 'vehicle' | 'category' | 'allergen' | 'child' | 'digest'
  data          TEXT NOT NULL,   -- JSON, see worker.js (ITEM_FIELDS)
  PRIMARY KEY (subscriber_id, pos)
);

CREATE TABLE IF NOT EXISTS sent (
  subscriber_id TEXT NOT NULL,
  recall_id     TEXT NOT NULL,
  at            TEXT NOT NULL,
  PRIMARY KEY (subscriber_id, recall_id)
);
CREATE INDEX IF NOT EXISTS sent_at ON sent (at);
