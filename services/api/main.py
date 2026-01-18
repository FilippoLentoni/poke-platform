import os
import uuid
from datetime import date
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import Json
import psycopg2

DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "poke")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

app = FastAPI(title="Poke Platform API")
_pool: Optional[SimpleConnectionPool] = None

class RejectBody(BaseModel):
    reason: Optional[str] = None

class ProposalIn(BaseModel):
    action: str
    asset_id: str
    qty: int = 1
    target_price: float
    confidence: float = 0.5
    rationale: Dict[str, Any] = {}

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
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_proposal (
                    proposal_id UUID PRIMARY KEY,
                    proposal_date DATE NOT NULL,
                    ts_created TIMESTAMPTZ NOT NULL DEFAULT now(),
                    action TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    qty INT NOT NULL,
                    target_price NUMERIC NOT NULL,
                    confidence NUMERIC NOT NULL,
                    rationale_json JSONB NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    decision TEXT NULL,
                    decision_reason TEXT NULL,
                    decided_ts TIMESTAMPTZ NULL
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS valuation_daily (
                    val_date DATE NOT NULL,
                    asset_id TEXT NOT NULL,
                    market_price NUMERIC NOT NULL,
                    smooth_price NUMERIC NOT NULL,
                    forecast_price NUMERIC NOT NULL,
                    gap NUMERIC NOT NULL,
                    gap_pct NUMERIC NOT NULL,
                    confidence NUMERIC NOT NULL DEFAULT 1.0,
                    rationale_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    strategy_name TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    run_id UUID NOT NULL,
                    ts_created TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (val_date, asset_id, strategy_name, strategy_version)
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_holding (
                    asset_id TEXT PRIMARY KEY,
                    qty INT NOT NULL DEFAULT 0,
                    avg_cost NUMERIC NULL,
                    updated_ts TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
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

@app.get("/api/proposals/today")
def proposals_today():
    if not db_enabled():
        return {"proposals": [], "note": "DB not configured"}
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT proposal_id, proposal_date, ts_created, action, asset_id, qty, target_price, confidence,
                       rationale_json, status, decision, decision_reason, decided_ts
                FROM trade_proposal
                WHERE proposal_date = %s
                ORDER BY ts_created DESC;
                """,
                (date.today(),),
            )
            rows = cur.fetchall()

        proposals = []
        for r in rows:
            proposals.append({
                "proposal_id": str(r[0]),
                "proposal_date": str(r[1]),
                "ts_created": r[2].isoformat(),
                "action": r[3],
                "asset_id": r[4],
                "qty": r[5],
                "target_price": float(r[6]),
                "confidence": float(r[7]),
                "rationale": r[8],
                "status": r[9],
                "decision": r[10],
                "decision_reason": r[11],
                "decided_ts": r[12].isoformat() if r[12] else None,
            })
        return {"proposals": proposals}
    finally:
        pool.putconn(conn)

def _fetch_valuations(order: str, limit: int, strategy_name: Optional[str], strategy_version: Optional[str]):
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            base = """
                WITH latest AS (
                    SELECT MAX(val_date) AS val_date FROM valuation_daily
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
                JOIN latest l ON vd.val_date = l.val_date
                LEFT JOIN card_metadata cm ON cm.asset_id = vd.asset_id
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


@app.get("/api/portfolio/valuations")
def portfolio_valuations():
    if not db_enabled():
        return {"holdings": [], "note": "DB not configured"}
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH latest AS (
                    SELECT MAX(val_date) AS val_date FROM valuation_daily
                )
                SELECT ph.asset_id,
                       ph.qty,
                       ph.avg_cost,
                       vd.market_price,
                       vd.forecast_price,
                       vd.gap_pct,
                       vd.confidence,
                       cm.name,
                       cm.artist,
                       cm.rarity,
                       cm.set_name
                FROM portfolio_holding ph
                LEFT JOIN latest l ON true
                LEFT JOIN valuation_daily vd
                    ON vd.asset_id = ph.asset_id AND vd.val_date = l.val_date
                LEFT JOIN card_metadata cm ON cm.asset_id = ph.asset_id
                ORDER BY ph.asset_id;
                """
            )
            rows = cur.fetchall()
        holdings = []
        for r in rows:
            holdings.append(
                {
                    "asset_id": r[0],
                    "qty": r[1],
                    "avg_cost": float(r[2]) if r[2] is not None else None,
                    "market_price": float(r[3]) if r[3] is not None else None,
                    "forecast_price": float(r[4]) if r[4] is not None else None,
                    "gap_pct": float(r[5]) if r[5] is not None else None,
                    "confidence": float(r[6]) if r[6] is not None else None,
                    "name": r[7],
                    "artist": r[8],
                    "rarity": r[9],
                    "set_name": r[10],
                }
            )
        return {"holdings": holdings}
    finally:
        pool.putconn(conn)

@app.post("/api/proposals/{proposal_id}/approve")
def approve(proposal_id: str):
    if not db_enabled():
        raise HTTPException(status_code=400, detail="DB not configured")
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE trade_proposal
                SET status='APPROVED', decision='APPROVE', decided_ts=now()
                WHERE proposal_id=%s
                """,
                (proposal_id,),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Proposal not found")
        conn.commit()
        return {"ok": True, "proposal_id": proposal_id}
    finally:
        pool.putconn(conn)

@app.post("/api/proposals/{proposal_id}/reject")
def reject(proposal_id: str, body: RejectBody):
    if not db_enabled():
        raise HTTPException(status_code=400, detail="DB not configured")
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE trade_proposal
                SET status='REJECTED', decision='REJECT', decision_reason=%s, decided_ts=now()
                WHERE proposal_id=%s
                """,
                (body.reason, proposal_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Proposal not found")
        conn.commit()
        return {"ok": True, "proposal_id": proposal_id}
    finally:
        pool.putconn(conn)

@app.post("/api/proposals/seed-demo")
def seed_demo():
    """
    Inserts demo proposals for today's review.
    Critical fixes:
      - Insert UUID as string (avoid psycopg2 'can't adapt type UUID')
      - Use Json(...) for JSONB (safe)
      - Return JSON even on error (so UI won't crash)
    """
    if not db_enabled():
        raise HTTPException(status_code=400, detail="DB not configured")

    demo: List[ProposalIn] = [
        ProposalIn(action="BUY",  asset_id="pokemon:sv4a:123", qty=1, target_price=42.0, confidence=0.73,
                   rationale={"why":"Undervalued vs comps", "signals":["artist_hype:komiya", "momentum:+7d"]}),
        ProposalIn(action="SELL", asset_id="pokemon:sv3:045", qty=1, target_price=18.5, confidence=0.61,
                   rationale={"why":"Over fair value; take-profit", "signals":["spread_widening"]}),
        ProposalIn(action="BUY",  asset_id="pokemon:sv5:201", qty=2, target_price=9.9, confidence=0.58,
                   rationale={"why":"Meta usage increasing", "signals":["meta_usage_delta:+12%"]}),
    ]

    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            for p in demo:
                pid = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO trade_proposal(
                        proposal_id, proposal_date, action, asset_id, qty, target_price, confidence, rationale_json, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
                    """,
                    (pid, date.today(), p.action, p.asset_id, p.qty, p.target_price, p.confidence, Json(p.rationale)),
                )
        conn.commit()
        return {"ok": True, "inserted": len(demo)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        pool.putconn(conn)
