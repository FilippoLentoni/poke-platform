import json
import os
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

import psycopg2
from psycopg2.extras import Json as PgJson, register_default_json, register_default_jsonb

DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "poke")
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]

SNAPSHOT_DATE = date.today()


def connect():
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=10,
    )
    register_default_jsonb(conn)
    register_default_json(conn)
    return conn


def ensure_tables(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
        CREATE TABLE IF NOT EXISTS tcgplayer_price_snapshot (
          snapshot_date      DATE        NOT NULL,
          snapshot_ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
          asset_id           TEXT        NOT NULL,
          variant            TEXT        NOT NULL,
          currency           TEXT        NOT NULL DEFAULT 'USD',
          market             NUMERIC     NULL,
          low                NUMERIC     NULL,
          mid                NUMERIC     NULL,
          high               NUMERIC     NULL,
          direct_low         NUMERIC     NULL,
          url                TEXT        NULL,
          source_updated_at  TEXT        NULL,
          extra              JSONB       NOT NULL DEFAULT '{}'::jsonb,
          PRIMARY KEY (snapshot_date, asset_id, variant)
        );
        """
        )
        cur.execute(
            """
        CREATE INDEX IF NOT EXISTS idx_tcgplayer_price_asset_date
          ON tcgplayer_price_snapshot(asset_id, snapshot_date);
        """
        )

        cur.execute(
            """
        CREATE TABLE IF NOT EXISTS cardmarket_price_snapshot (
          snapshot_date      DATE        NOT NULL,
          snapshot_ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
          asset_id           TEXT        NOT NULL,
          variant            TEXT        NOT NULL DEFAULT 'default',
          currency           TEXT        NOT NULL DEFAULT 'EUR',
          avg1               NUMERIC     NULL,
          avg7               NUMERIC     NULL,
          avg30              NUMERIC     NULL,
          low_price          NUMERIC     NULL,
          trend_price        NUMERIC     NULL,
          url                TEXT        NULL,
          source_updated_at  TEXT        NULL,
          extra              JSONB       NOT NULL DEFAULT '{}'::jsonb,
          PRIMARY KEY (snapshot_date, asset_id, variant)
        );
        """
        )
        cur.execute(
            """
        CREATE INDEX IF NOT EXISTS idx_cardmarket_price_asset_date
          ON cardmarket_price_snapshot(asset_id, snapshot_date);
        """
        )
    conn.commit()


def to_num(x) -> Optional[Decimal]:
    if x is None:
        return None
    try:
        return Decimal(str(x))
    except Exception:
        return None


def parse_raw_json(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


def upsert_tcgplayer(cur, asset_id: str, tcg: Dict[str, Any]):
    url = tcg.get("url")
    updated_at = tcg.get("updatedAt")
    prices = tcg.get("prices") or {}
    for variant, v in prices.items():
        if not isinstance(v, dict):
            continue
        cur.execute(
            """
            INSERT INTO tcgplayer_price_snapshot(
              snapshot_date, asset_id, variant, market, low, mid, high, direct_low, url, source_updated_at, extra
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (snapshot_date, asset_id, variant) DO UPDATE SET
              snapshot_ts=now(),
              market=EXCLUDED.market,
              low=EXCLUDED.low,
              mid=EXCLUDED.mid,
              high=EXCLUDED.high,
              direct_low=EXCLUDED.direct_low,
              url=EXCLUDED.url,
              source_updated_at=EXCLUDED.source_updated_at,
              extra=EXCLUDED.extra;
            """,
            (
                SNAPSHOT_DATE,
                asset_id,
                variant,
                to_num(v.get("market")),
                to_num(v.get("low")),
                to_num(v.get("mid")),
                to_num(v.get("high")),
                to_num(v.get("directLow")),
                url,
                updated_at,
                PgJson(v),
            ),
        )


def upsert_cardmarket(cur, asset_id: str, cm: Dict[str, Any]):
    url = cm.get("url")
    updated_at = cm.get("updatedAt")
    prices = cm.get("prices") or {}
    if not isinstance(prices, dict):
        return

    cur.execute(
        """
        INSERT INTO cardmarket_price_snapshot(
          snapshot_date, asset_id, variant, avg1, avg7, avg30, low_price, trend_price, url, source_updated_at, extra
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (snapshot_date, asset_id, variant) DO UPDATE SET
          snapshot_ts=now(),
          avg1=EXCLUDED.avg1,
          avg7=EXCLUDED.avg7,
          avg30=EXCLUDED.avg30,
          low_price=EXCLUDED.low_price,
          trend_price=EXCLUDED.trend_price,
          url=EXCLUDED.url,
          source_updated_at=EXCLUDED.source_updated_at,
          extra=EXCLUDED.extra;
        """,
        (
            SNAPSHOT_DATE,
            asset_id,
            "default",
            to_num(prices.get("avg1")),
            to_num(prices.get("avg7")),
            to_num(prices.get("avg30")),
            to_num(prices.get("lowPrice")),
            to_num(prices.get("trendPrice")),
            url,
            updated_at,
            PgJson(prices),
        ),
    )

    reverse_keys = [
        "reverseHoloAvg1",
        "reverseHoloAvg7",
        "reverseHoloAvg30",
        "reverseHoloTrend",
        "reverseHoloSell",
    ]
    if any(k in prices for k in reverse_keys):
        cur.execute(
            """
            INSERT INTO cardmarket_price_snapshot(
              snapshot_date, asset_id, variant, avg1, avg7, avg30, low_price, trend_price, url, source_updated_at, extra
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (snapshot_date, asset_id, variant) DO UPDATE SET
              snapshot_ts=now(),
              avg1=EXCLUDED.avg1,
              avg7=EXCLUDED.avg7,
              avg30=EXCLUDED.avg30,
              low_price=EXCLUDED.low_price,
              trend_price=EXCLUDED.trend_price,
              url=EXCLUDED.url,
              source_updated_at=EXCLUDED.source_updated_at,
              extra=EXCLUDED.extra;
            """,
            (
                SNAPSHOT_DATE,
                asset_id,
                "reverseHolo",
                to_num(prices.get("reverseHoloAvg1")),
                to_num(prices.get("reverseHoloAvg7")),
                to_num(prices.get("reverseHoloAvg30")),
                None,
                to_num(prices.get("reverseHoloTrend")),
                url,
                updated_at,
                PgJson({k: prices.get(k) for k in reverse_keys if k in prices}),
            ),
        )


def main():
    conn = connect()
    try:
        ensure_tables(conn)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ta.asset_id, cm.raw_json
                FROM tracked_asset ta
                JOIN card_metadata cm ON cm.asset_id = ta.asset_id
                WHERE ta.is_active = true;
                """
            )
            rows = cur.fetchall()

        total = len(rows)
        tcg_rows = 0
        cm_rows = 0

        with conn.cursor() as cur:
            for asset_id, raw in rows:
                doc = parse_raw_json(raw)

                tcg = doc.get("tcgplayer")
                if isinstance(tcg, dict) and isinstance(tcg.get("prices"), dict):
                    upsert_tcgplayer(cur, asset_id, tcg)
                    tcg_rows += 1

                cm = doc.get("cardmarket")
                if isinstance(cm, dict) and isinstance(cm.get("prices"), dict):
                    upsert_cardmarket(cur, asset_id, cm)
                    cm_rows += 1

            conn.commit()

        print(
            "price_extractor done: "
            f"assets={total} tcgplayer_assets={tcg_rows} "
            f"cardmarket_assets={cm_rows} date={SNAPSHOT_DATE}"
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
