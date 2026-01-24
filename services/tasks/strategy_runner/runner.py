import os
import uuid
import importlib
from datetime import date
from typing import Any, Dict

import psycopg2

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
    conn.commit()


def load_strategy():
    mod = importlib.import_module(f"strategies.{STRATEGY_NAME}")
    if not hasattr(mod, "generate_proposals"):
        raise RuntimeError(
            f"Strategy {STRATEGY_NAME} missing generate_proposals(context)"
        )
    return mod


def main():
    conn = connect()
    try:
        ensure_schema(conn)

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
        strategy.generate_proposals(context)

        print(
            f"Strategy run complete: {STRATEGY_NAME}@{STRATEGY_VERSION} run_id={run_id}"
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
