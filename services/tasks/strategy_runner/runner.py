import os
import uuid
import importlib
from datetime import date
from typing import Any, Dict, List

import psycopg2
from psycopg2.extras import Json

DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "poke")
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]

STRATEGY_NAME = os.environ.get("STRATEGY_NAME", "baseline_spread")
STRATEGY_VERSION = os.environ.get("STRATEGY_VERSION", "v1")


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
        # Existing proposals table (if not created yet by API)
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

        # Valuation output table for strategy results
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
            CREATE INDEX IF NOT EXISTS idx_valuation_daily_gap
              ON valuation_daily(val_date, gap_pct);
            """
        )

        # Strategy run audit table
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_run (
                run_id UUID PRIMARY KEY,
                run_date DATE NOT NULL,
                ts_started TIMESTAMPTZ NOT NULL DEFAULT now(),
                strategy_name TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                inserted_proposals INT NOT NULL DEFAULT 0,
                note TEXT NULL
            );
            """
        )

        # Optional: link proposals to strategy run (minimal)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS proposal_run_link (
                run_id UUID NOT NULL,
                proposal_id UUID NOT NULL,
                PRIMARY KEY (run_id, proposal_id)
            );
            """
        )
    conn.commit()


def already_ran_today(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(1) FROM strategy_run WHERE run_date=%s AND strategy_name=%s AND strategy_version=%s;",
            (date.today(), STRATEGY_NAME, STRATEGY_VERSION),
        )
        return cur.fetchone()[0] > 0


def load_strategy():
    mod = importlib.import_module(f"strategies.{STRATEGY_NAME}")
    if not hasattr(mod, "generate_proposals"):
        raise RuntimeError(
            f"Strategy {STRATEGY_NAME} missing generate_proposals(context)"
        )
    return mod


def insert_proposals(conn, run_id: str, proposals: List[Dict[str, Any]]) -> int:
    inserted = 0
    with conn.cursor() as cur:
        for p in proposals:
            pid = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO trade_proposal(
                    proposal_id, proposal_date, action, asset_id, qty, target_price, confidence, rationale_json, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
                """,
                (
                    pid,
                    date.today(),
                    p["action"],
                    p["asset_id"],
                    int(p.get("qty", 1)),
                    float(p["target_price"]),
                    float(p.get("confidence", 0.5)),
                    Json(p.get("rationale", {})),
                ),
            )
            cur.execute(
                "INSERT INTO proposal_run_link(run_id, proposal_id) VALUES (%s, %s);",
                (run_id, pid),
            )
            inserted += 1
    conn.commit()
    return inserted


def main():
    conn = connect()
    try:
        ensure_schema(conn)

        if already_ran_today(conn):
            print(
                f"Already ran today for {STRATEGY_NAME}@{STRATEGY_VERSION}. Exiting."
            )
            return

        run_id = str(uuid.uuid4())

        # Context is minimal now; will be extended later
        context = {
            "run_date": date.today().isoformat(),
            "strategy_name": STRATEGY_NAME,
            "strategy_version": STRATEGY_VERSION,
            "run_id": run_id,
            "db_conn": conn,
            "signals": [],
            "observations": [],
            "portfolio": {},
        }

        strategy = load_strategy()
        proposals = strategy.generate_proposals(context)

        inserted = insert_proposals(conn, run_id, proposals)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO strategy_run(run_id, run_date, strategy_name, strategy_version, inserted_proposals, note)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (
                    run_id,
                    date.today(),
                    STRATEGY_NAME,
                    STRATEGY_VERSION,
                    inserted,
                    "ok",
                ),
            )
        conn.commit()

        print(
            f"Strategy run complete: {STRATEGY_NAME}@{STRATEGY_VERSION} inserted={inserted} run_id={run_id}"
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
