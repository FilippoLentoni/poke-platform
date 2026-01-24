#!/usr/bin/env python3

import argparse
import os

import psycopg2


def connect():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "poke"),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=10,
    )


def fetch_price_history(conn, asset_id: str) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT snapshot_date,
                   'tcgplayer' AS source,
                   variant,
                   market,
                   low,
                   mid,
                   high,
                   direct_low,
                   NULL::numeric AS avg1,
                   NULL::numeric AS avg7,
                   NULL::numeric AS avg30,
                   NULL::numeric AS low_price,
                   NULL::numeric AS trend_price,
                   currency,
                   url,
                   source_updated_at
            FROM tcgplayer_price_snapshot
            WHERE asset_id = %s
            UNION ALL
            SELECT snapshot_date,
                   'cardmarket' AS source,
                   variant,
                   NULL::numeric AS market,
                   NULL::numeric AS low,
                   NULL::numeric AS mid,
                   NULL::numeric AS high,
                   NULL::numeric AS direct_low,
                   avg1,
                   avg7,
                   avg30,
                   low_price,
                   trend_price,
                   currency,
                   url,
                   source_updated_at
            FROM cardmarket_price_snapshot
            WHERE asset_id = %s
            ORDER BY snapshot_date DESC, source, variant;
            """,
            (asset_id, asset_id),
        )
        return cur.fetchall()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print price history for a card id from TCGPlayer and Cardmarket."
    )
    parser.add_argument(
        "card_id",
        help="Card asset id, e.g. ptcg:sm115-24",
    )
    args = parser.parse_args()

    conn = connect()
    try:
        rows = fetch_price_history(conn, args.card_id)
    finally:
        conn.close()

    columns = [
        "snapshot_date",
        "source",
        "variant",
        "market",
        "low",
        "mid",
        "high",
        "direct_low",
        "avg1",
        "avg7",
        "avg30",
        "low_price",
        "trend_price",
        "currency",
        "url",
        "source_updated_at",
    ]
    if not rows:
        print(f"No price history found for {args.card_id}.")
        return

    try:
        import pandas as pd
    except ImportError:
        pd = None

    if pd is not None:
        df = pd.DataFrame(rows, columns=columns)
        print(df.to_string(index=False))
        return

    widths = [len(c) for c in columns]
    formatted_rows = []
    for row in rows:
        formatted = ["" if v is None else str(v) for v in row]
        formatted_rows.append(formatted)
        widths = [max(w, len(v)) for w, v in zip(widths, formatted)]

    header = " | ".join(c.ljust(w) for c, w in zip(columns, widths))
    sep = "-+-".join("-" * w for w in widths)
    print(header)
    print(sep)
    for formatted in formatted_rows:
        print(" | ".join(v.ljust(w) for v, w in zip(formatted, widths)))


if __name__ == "__main__":
    main()
