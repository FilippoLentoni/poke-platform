import os
from collections import defaultdict
from datetime import date, timedelta

from psycopg2.extras import Json

DEFAULT_ALPHA = float(os.getenv("SES_ALPHA", "0.2"))
LOOKBACK_DAYS = int(os.getenv("SES_LOOKBACK_DAYS", "120"))
MIN_MARKET_PRICE = float(os.getenv("SES_MIN_PRICE", "0"))

PREFERRED_VARIANTS = ["normal", "reverseHolofoil"]


def _fetch_price_history(conn, start_date: date) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.snapshot_date, t.asset_id, t.variant, t.market
            FROM tcgplayer_price_snapshot t
            JOIN tracked_asset ta ON ta.asset_id = t.asset_id
            WHERE ta.is_active = true
              AND (ta.tags->>'rarity') ILIKE %s
              AND t.snapshot_date >= %s
              AND t.market IS NOT NULL
              AND t.market > %s
              AND t.variant IN ('normal', 'reverseHolofoil')
            ORDER BY t.asset_id, t.variant, t.snapshot_date;
            """,
            ("%Rare%", start_date, MIN_MARKET_PRICE),
        )
        return cur.fetchall()


def _choose_variant(variants: dict, target_date: date) -> tuple[str | None, list[tuple]]:
    for variant in PREFERRED_VARIANTS:
        rows = variants.get(variant, [])
        if any(d == target_date for d, _ in rows):
            return variant, rows
    for variant in PREFERRED_VARIANTS:
        rows = variants.get(variant, [])
        if rows:
            return variant, rows
    return None, []


def _compute_ses(prices: list[tuple], alpha: float) -> tuple[float, float]:
    if not prices:
        return 0.0, 0.0
    s = float(prices[0][1])
    for _, price in prices[1:]:
        s = (alpha * float(price)) + ((1 - alpha) * s)
    return s, float(prices[-1][1])


def generate_proposals(context: dict) -> list[dict]:
    conn = context["db_conn"]
    run_id = context["run_id"]
    strategy_name = context["strategy_name"]
    strategy_version = context["strategy_version"]

    today = date.today()
    start_date = today - timedelta(days=LOOKBACK_DAYS)
    history_rows = _fetch_price_history(conn, start_date)

    asset_variants = defaultdict(lambda: defaultdict(list))
    for snap_date, asset_id, variant, market in history_rows:
        asset_variants[asset_id][variant].append((snap_date, market))

    inserts = []
    for asset_id, variants in asset_variants.items():
        variant, rows = _choose_variant(variants, today)
        if not rows:
            continue
        rows.sort(key=lambda r: r[0])
        last_date = rows[-1][0]
        if last_date != today:
            continue

        smooth_price, market_price = _compute_ses(rows, DEFAULT_ALPHA)
        if market_price <= 0:
            continue

        forecast_price = smooth_price
        gap = forecast_price - market_price
        gap_pct = gap / market_price

        inserts.append(
            (
                last_date,
                asset_id,
                market_price,
                smooth_price,
                forecast_price,
                gap,
                gap_pct,
                1.0,
                Json(
                    {
                        "alpha": DEFAULT_ALPHA,
                        "variant": variant,
                        "lookback_days": LOOKBACK_DAYS,
                        "price_points": len(rows),
                        "last_price_date": last_date.isoformat(),
                    }
                ),
                strategy_name,
                strategy_version,
                run_id,
            )
        )

    if inserts:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO valuation_daily(
                    val_date,
                    asset_id,
                    market_price,
                    smooth_price,
                    forecast_price,
                    gap,
                    gap_pct,
                    confidence,
                    rationale_json,
                    strategy_name,
                    strategy_version,
                    run_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (val_date, asset_id, strategy_name, strategy_version) DO UPDATE SET
                    market_price=EXCLUDED.market_price,
                    smooth_price=EXCLUDED.smooth_price,
                    forecast_price=EXCLUDED.forecast_price,
                    gap=EXCLUDED.gap,
                    gap_pct=EXCLUDED.gap_pct,
                    confidence=EXCLUDED.confidence,
                    rationale_json=EXCLUDED.rationale_json,
                    run_id=EXCLUDED.run_id,
                    ts_created=now();
                """,
                inserts,
            )
        conn.commit()

    return []
