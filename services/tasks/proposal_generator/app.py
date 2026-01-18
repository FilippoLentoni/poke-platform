import os
import uuid
from datetime import date
from typing import List, Dict, Any

import psycopg2
from psycopg2.extras import Json

DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "poke")
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]

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
    conn.commit()

def already_seeded_today(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(1) FROM trade_proposal WHERE proposal_date = %s;", (date.today(),))
        n = cur.fetchone()[0]
        return n > 0

def generate_demo_proposals() -> List[Dict[str, Any]]:
    # Later replace with real strategy outputs
    return [
        {
            "action": "BUY",
            "asset_id": "pokemon:sv4a:123",
            "qty": 1,
            "target_price": 42.0,
            "confidence": 0.73,
            "rationale": {"why": "Undervalued vs comps", "signals": ["artist_hype:komiya", "momentum:+7d"]},
        },
        {
            "action": "SELL",
            "asset_id": "pokemon:sv3:045",
            "qty": 1,
            "target_price": 18.5,
            "confidence": 0.61,
            "rationale": {"why": "Over fair value; take-profit", "signals": ["spread_widening"]},
        },
        {
            "action": "BUY",
            "asset_id": "pokemon:sv5:201",
            "qty": 2,
            "target_price": 9.9,
            "confidence": 0.58,
            "rationale": {"why": "Meta usage increasing", "signals": ["meta_usage_delta:+12%"]},
        },
    ]

def insert_proposals(conn, proposals: List[Dict[str, Any]]):
    with conn.cursor() as cur:
        for p in proposals:
            pid = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO trade_proposal(
                    proposal_id, proposal_date, action, asset_id, qty, target_price, confidence, rationale_json, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
                """,
                (pid, date.today(), p["action"], p["asset_id"], p["qty"], p["target_price"], p["confidence"], Json(p["rationale"])),
            )
    conn.commit()

def main():
    conn = connect()
    try:
        ensure_schema(conn)
        if already_seeded_today(conn):
            print("Already seeded today. Exiting.")
            return
        proposals = generate_demo_proposals()
        insert_proposals(conn, proposals)
        print(f"Inserted {len(proposals)} proposals for {date.today().isoformat()}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()


