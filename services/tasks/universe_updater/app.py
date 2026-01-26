import os
from datetime import datetime, date

import psycopg2
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from psycopg2.extras import Json

DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "poke")
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]

PTCG_API_KEY = os.environ.get("PTCG_API_KEY")

BASE = "https://api.pokemontcg.io/v2"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "poke-platform-universe-updater/1.0"})
SESSION.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=5,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
    ),
)


def connect():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=10,
    )


def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
        CREATE TABLE IF NOT EXISTS card_metadata (
            asset_id TEXT NOT NULL,
            snapshot_date DATE NOT NULL,
            ptcg_card_id TEXT,
            name TEXT,
            set_id TEXT,
            set_name TEXT,
            set_release_date DATE NULL,
            number TEXT NULL,
            rarity TEXT NULL,
            artist TEXT NULL,
            images_json JSONB NULL,
            raw_json JSONB NULL,
            updated_ts TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (asset_id, snapshot_date)
        );
        """
        )
        cur.execute(
            """
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        WHERE t.relname = 'card_metadata'
          AND c.contype = 'p';
        """
        )
        if cur.fetchone() is None:
            cur.execute(
                """
            ALTER TABLE card_metadata
            ADD CONSTRAINT card_metadata_pkey PRIMARY KEY (asset_id, snapshot_date);
            """
            )
        cur.execute(
            """
        CREATE INDEX IF NOT EXISTS idx_card_metadata_asset_date
          ON card_metadata(asset_id, snapshot_date DESC);
        """
        )
    conn.commit()


def headers():
    h = {}
    if PTCG_API_KEY:
        h["X-Api-Key"] = PTCG_API_KEY
    return h


def get_sets():
    sets = []
    page = 1
    while True:
        r = SESSION.get(
            f"{BASE}/sets",
            params={"page": page, "pageSize": 250},
            headers=headers(),
            timeout=(10, 120),
        )
        r.raise_for_status()
        data = r.json()
        sets.extend(data.get("data", []))
        if page >= data.get("totalPages", 1):
            break
        page += 1
    return sets


def iter_cards_for_set(set_id: str):
    page = 1
    while True:
        r = SESSION.get(
            f"{BASE}/cards",
            params={"q": f"set.id:{set_id}", "page": page, "pageSize": 100},
            headers=headers(),
            timeout=(10, 120),
        )
        r.raise_for_status()
        data = r.json()
        yield page, data.get("totalCount"), data.get("data", [])
        if page >= data.get("totalPages", 1):
            break
        page += 1


def parse_release_date(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y/%m/%d").date()
    except Exception:
        return None


def upsert_card(conn, card: dict, set_release_date: date | None):
    ptcg_id = card.get("id")
    asset_id = f"ptcg:{ptcg_id}"
    snapshot_date = date.today()
    name = card.get("name")
    set_obj = card.get("set", {}) or {}
    set_id = set_obj.get("id")
    set_name = set_obj.get("name")
    number = card.get("number")
    rarity = card.get("rarity")
    artist = card.get("artist")
    images = card.get("images")

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO card_metadata(
              asset_id, snapshot_date, ptcg_card_id, name, set_id, set_name,
              set_release_date, number, rarity, artist, images_json, raw_json
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (asset_id, snapshot_date) DO UPDATE SET
              name=EXCLUDED.name,
              set_id=EXCLUDED.set_id,
              set_name=EXCLUDED.set_name,
              set_release_date=EXCLUDED.set_release_date,
              number=EXCLUDED.number,
              rarity=EXCLUDED.rarity,
              artist=EXCLUDED.artist,
              images_json=EXCLUDED.images_json,
              raw_json=EXCLUDED.raw_json,
              updated_ts=now();
            """,
            (
                asset_id,
                snapshot_date,
                ptcg_id,
                name,
                set_id,
                set_name,
                set_release_date,
                number,
                rarity,
                artist,
                Json(images),
                Json(card),
            ),
        )


def main():
    conn = connect()
    new_sets = 0
    new_cards = 0

    try:
        ensure_schema(conn)

        sets = get_sets()
        print(f"Fetched {len(sets)} sets", flush=True)
        cutoff = date.today().toordinal() - (365 * 10)

        for s in sets:
            rel = parse_release_date(s.get("releaseDate") or "")
            if rel and rel.toordinal() < cutoff:
                continue

            set_id = s.get("id")
            set_name = s.get("name")
            print(f"Processing set {set_id} ({set_name})", flush=True)
            try:
                for page, total_count, cards in iter_cards_for_set(set_id):
                    if page == 1:
                        print(
                            f"Set {set_id} totalCount={total_count}",
                            flush=True,
                        )
                    if cards:
                        new_sets += 1 if page == 1 else 0
                    for c in cards:
                        upsert_card(conn, c, rel)
                        new_cards += 1
                    conn.commit()
                    print(
                        f"Set {set_id} page {page} inserted {len(cards)}",
                        flush=True,
                    )
            except Exception as exc:
                print(f"Set {set_id} failed: {exc}", flush=True)
                conn.rollback()

        print(f"Universe update done. new_sets={new_sets} new_cards={new_cards}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
