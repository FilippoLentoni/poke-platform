import os
from datetime import date
from typing import Optional, Dict, Any, List

from fastapi import FastAPI
from psycopg2.pool import SimpleConnectionPool
import psycopg2

DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "poke")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

app = FastAPI(title="Poke Platform API")
_pool: Optional[SimpleConnectionPool] = None

def db_enabled() -> bool:
    return all([DB_HOST, DB_USER, DB_PASSWORD])

def get_pool() -> SimpleConnectionPool:
    global _pool
    if _pool is None:
        if not db_enabled():
            raise RuntimeError("DB not configured")
        _pool = SimpleConnectionPool(
            minconn=1,
            maxconn=5,
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            connect_timeout=5,
        )
    return _pool

def init_db() -> None:
    pool = get_pool()
    conn = pool.getconn()
    try:
        conn.commit()
    finally:
        pool.putconn(conn)

@app.on_event("startup")
def startup():
    if db_enabled():
        init_db()

@app.get("/api/health")
def health():
    return {"ok": True, "service": "api", "db": db_enabled()}

def _fetch_valuations(order: str, limit: int, strategy_name: Optional[str], strategy_version: Optional[str]):
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            base = """
                WITH latest_val AS (
                    SELECT MAX(val_date) AS val_date FROM valuation_daily
                ),
                latest_card AS (
                    SELECT DISTINCT ON (asset_id)
                        asset_id,
                        name,
                        artist,
                        rarity,
                        set_name
                    FROM card_metadata
                    ORDER BY asset_id, snapshot_date DESC, updated_ts DESC
                )
                SELECT vd.val_date,
                       vd.asset_id,
                       vd.market_price,
                       vd.forecast_price,
                       vd.gap,
                       vd.gap_pct,
                       vd.confidence,
                       vd.rationale_json,
                       cm.name,
                       cm.artist,
                       cm.rarity,
                       cm.set_name
                FROM valuation_daily vd
                JOIN latest_val l ON vd.val_date = l.val_date
                LEFT JOIN latest_card cm ON cm.asset_id = vd.asset_id
            """
            params: List[Any] = []
            clauses = []
            if strategy_name:
                clauses.append("vd.strategy_name = %s")
                params.append(strategy_name)
            if strategy_version:
                clauses.append("vd.strategy_version = %s")
                params.append(strategy_version)
            if clauses:
                base += " WHERE " + " AND ".join(clauses)
            base += f" ORDER BY vd.gap_pct {order} LIMIT %s;"
            params.append(limit)
            cur.execute(base, params)
            rows = cur.fetchall()

        valuations = []
        for r in rows:
            valuations.append(
                {
                    "val_date": str(r[0]),
                    "asset_id": r[1],
                    "market_price": float(r[2]),
                    "forecast_price": float(r[3]),
                    "gap": float(r[4]),
                    "gap_pct": float(r[5]),
                    "confidence": float(r[6]),
                    "rationale": r[7],
                    "name": r[8],
                    "artist": r[9],
                    "rarity": r[10],
                    "set_name": r[11],
                }
            )
        return {"valuations": valuations}
    finally:
        pool.putconn(conn)


@app.get("/api/valuations/undervalued")
def valuations_undervalued(limit: int = 10, strategy_name: Optional[str] = None, strategy_version: Optional[str] = None):
    if not db_enabled():
        return {"valuations": [], "note": "DB not configured"}
    return _fetch_valuations("DESC", limit, strategy_name, strategy_version)


@app.get("/api/valuations/overvalued")
def valuations_overvalued(limit: int = 10, strategy_name: Optional[str] = None, strategy_version: Optional[str] = None):
    if not db_enabled():
        return {"valuations": [], "note": "DB not configured"}
    return _fetch_valuations("ASC", limit, strategy_name, strategy_version)
