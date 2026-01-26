from __future__ import annotations

import os
import datetime as dt
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

import psycopg2
import psycopg2.extras


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str
    sslmode: str = "require"


def load_postgres_config_from_env() -> Optional[PostgresConfig]:
    """
    Expected env vars (match your existing repo style):
      DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
    """
    host = os.getenv("DB_HOST")
    dbname = os.getenv("DB_NAME")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    if not all([host, dbname, user, password]):
        return None

    return PostgresConfig(
        host=host,
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=dbname,
        user=user,
        password=password,
        sslmode=os.getenv("DB_SSLMODE", "require"),
    )


def _connect(cfg: PostgresConfig):
    return psycopg2.connect(
        host=cfg.host,
        port=cfg.port,
        dbname=cfg.dbname,
        user=cfg.user,
        password=cfg.password,
        sslmode=cfg.sslmode,
    )


def fetch_price_history_from_postgres(
    cfg: PostgresConfig,
    card_name: str,
    market: str = "cardmarket",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 365,
) -> List[Dict[str, Any]]:
    """
    IMPORTANT: You MUST adapt the SQL to your actual schema.
    Using cardmarket_price_snapshot (your current schema).

    Return:
      [{"date": "YYYY-MM-DD", "price": 12.34, "currency": "EUR", "market": "cardmarket"}, ...]
    """
    if market != "cardmarket":
        return []

    if end_date is None:
        end_date = dt.date.today().isoformat()
    if start_date is None:
        start_date = (dt.date.today() - dt.timedelta(days=365)).isoformat()

    sql = """
    SELECT
      to_char(snapshot_date, 'YYYY-MM-DD') AS date,
      COALESCE(trend_price, avg1, avg7, avg30) AS price,
      currency AS currency
    FROM cardmarket_price_snapshot
    WHERE name ILIKE %(card_name)s
      AND snapshot_date BETWEEN %(start_date)s::date AND %(end_date)s::date
    ORDER BY snapshot_date ASC
    LIMIT %(limit)s
    """

    params = dict(
        card_name=f"%{card_name}%",
        market=market,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )

    with _connect(cfg) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    out = []
    for r in rows:
        out.append(
            {
                "date": r["date"],
                "price": float(r["price"]) if r["price"] is not None else None,
                "currency": r.get("currency"),
                "market": "cardmarket",
            }
        )
    return out
