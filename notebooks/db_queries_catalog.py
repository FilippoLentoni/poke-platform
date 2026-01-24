"""Catalog of database tables and example queries for poke-platform."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class JoinKey:
    left: str
    right: str
    description: str


@dataclass(frozen=True)
class QueryInfo:
    name: str
    sql: str
    description: str
    join_keys: List[str]


TABLES = {
    "card_metadata": {
        "description": "Daily snapshots of Pokemon card metadata from the PTCG API.",
        "columns": [
            "asset_id",
            "snapshot_date",
            "ptcg_card_id",
            "name",
            "set_id",
            "set_name",
            "set_release_date",
            "number",
            "rarity",
            "artist",
            "images_json",
            "raw_json",
            "updated_ts",
        ],
    },
    "tcgplayer_price_snapshot": {
        "description": "Daily price snapshots from TCGplayer per asset/variant.",
        "columns": [
            "snapshot_date",
            "snapshot_ts",
            "asset_id",
            "ptcg_card_id",
            "name",
            "set_id",
            "set_name",
            "set_release_date",
            "number",
            "rarity",
            "artist",
            "images_json",
            "variant",
            "currency",
            "market",
            "low",
            "mid",
            "high",
            "direct_low",
            "url",
            "source_updated_at",
            "extra",
        ],
    },
    "cardmarket_price_snapshot": {
        "description": "Daily price snapshots from Cardmarket per asset/variant.",
        "columns": [
            "snapshot_date",
            "snapshot_ts",
            "asset_id",
            "ptcg_card_id",
            "name",
            "set_id",
            "set_name",
            "set_release_date",
            "number",
            "rarity",
            "artist",
            "images_json",
            "variant",
            "currency",
            "avg1",
            "avg7",
            "avg30",
            "low_price",
            "trend_price",
            "url",
            "source_updated_at",
            "extra",
        ],
    },
    "valuation_daily": {
        "description": "Daily valuation outputs from strategies.",
        "columns": [
            "val_date",
            "asset_id",
            "market_price",
            "smooth_price",
            "forecast_price",
            "gap",
            "gap_pct",
            "confidence",
            "rationale_json",
            "strategy_name",
            "strategy_version",
            "run_id",
            "ts_created",
        ],
    },
}


JOIN_KEYS = []


QUERIES = [
    QueryInfo(
        name="card_metadata_count",
        sql="SELECT COUNT(*) AS card_metadata_snapshot_count FROM card_metadata;",
        description="Total number of card metadata snapshots.",
        join_keys=[],
    ),
    QueryInfo(
        name="latest_metadata_snapshot",
        sql="SELECT MAX(snapshot_date) AS latest_snapshot_date FROM card_metadata;",
        description="Most recent snapshot date for metadata.",
        join_keys=[],
    ),
    QueryInfo(
        name="recent_cards",
        sql=(
            "SELECT asset_id, name, set_name, rarity, snapshot_date, updated_ts "
            "FROM ("
            "  SELECT DISTINCT ON (asset_id) asset_id, name, set_name, rarity, snapshot_date, updated_ts "
            "  FROM card_metadata "
            "  ORDER BY asset_id, snapshot_date DESC, updated_ts DESC"
            ") t "
            "ORDER BY snapshot_date DESC, updated_ts DESC LIMIT 50;"
        ),
        description="Sample of recently updated cards (latest snapshot per asset).",
        join_keys=[],
    ),
    QueryInfo(
        name="tcgplayer_latest_prices",
        sql=(
            "SELECT asset_id, variant, market, low, mid, high, snapshot_date "
            "FROM tcgplayer_price_snapshot "
            "ORDER BY snapshot_date DESC LIMIT 50;"
        ),
        description="Latest TCGplayer price snapshots.",
        join_keys=[],
    ),
    QueryInfo(
        name="cardmarket_latest_prices",
        sql=(
            "SELECT asset_id, variant, avg1, avg7, avg30, trend_price, snapshot_date "
            "FROM cardmarket_price_snapshot "
            "ORDER BY snapshot_date DESC LIMIT 50;"
        ),
        description="Latest Cardmarket price snapshots.",
        join_keys=[],
    ),
    QueryInfo(
        name="latest_valuations",
        sql=(
            "WITH latest_val AS (SELECT MAX(val_date) AS val_date FROM valuation_daily) "
            "SELECT val_date, asset_id, market_price, forecast_price, gap_pct, confidence "
            "FROM valuation_daily WHERE val_date = (SELECT val_date FROM latest_val) "
            "ORDER BY gap_pct DESC LIMIT 50;"
        ),
        description="Latest valuation outputs.",
        join_keys=[],
    ),
]


def example_usage() -> None:
    """Example of wiring to read_sql from scripts.db_notebook_helpers."""
    # from scripts.db_notebook_helpers import read_sql
    # from notebooks.db_explore import REGION, SECRET_ARN
    # df = read_sql(QUERIES[0].sql, region=REGION, secret_arn=SECRET_ARN)
    # print(df.head())
    raise SystemExit("Import this module and use QUERIES with read_sql().")
