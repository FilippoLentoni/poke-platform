#!/usr/bin/env python3

# to test
# export REGION=us-east-2
# export STACK=PokePlatformStack

# SCRIPT_B64=$(base64 -w 0 scripts/strategy_exploration.py)

# CLUSTER_ARN=$(AWS_PAGER="" aws --region "$REGION" ecs list-clusters --output text | awk '{print $2}')
# SERVICE_ARN=$(AWS_PAGER="" aws --region "$REGION" cloudformation list-stack-resources \
#   --stack-name "$STACK" \
#   --query "StackResourceSummaries[?ResourceType=='AWS::ECS::Service'].PhysicalResourceId" \
#   --output text | awk '{print $1}')
# SERVICE_NAME=$(printf "%s" "$SERVICE_ARN" | awk -F/ '{print $NF}' | tr -d '\r' | xargs)

# TASK_ARN=$(AWS_PAGER="" aws --region "$REGION" ecs list-tasks \
#   --cluster "$CLUSTER_ARN" \
#   --service-name "$SERVICE_NAME" \
#   --desired-status RUNNING \
#   --max-items 1 \
#   --query "taskArns[0]" \
#   --output text)

# AWS_PAGER="" aws --region "$REGION" ecs execute-command \
#   --cluster "$CLUSTER_ARN" \
#   --task "$TASK_ARN" \
#   --container "ApiContainer" \
#   --interactive \
#   --command "bash -lc 'echo $SCRIPT_B64 | base64 -d > /tmp/strategy_exploration.py && python /tmp/strategy_exploration.py'"



import os
from collections import defaultdict
from datetime import date, timedelta

import psycopg2

LOOKBACK_DAYS = int(os.getenv("SES_LOOKBACK_DAYS", "30"))
DEFAULT_ALPHA = float(os.getenv("SES_ALPHA", "0.2"))
MIN_MARKET_PRICE = float(os.getenv("SES_MIN_PRICE", "0"))

PREFERRED_VARIANTS = ["normal", "reverseHolofoil", "holofoil"]


def connect():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "poke"),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=10,
    )


def fetch_price_history(conn, start_date: date):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.snapshot_date, t.asset_id, t.variant, t.market
            FROM tcgplayer_price_snapshot t
            JOIN tracked_asset ta ON ta.asset_id = t.asset_id
            WHERE ta.is_active = true
              AND t.snapshot_date >= %s
              AND t.market IS NOT NULL
              AND t.market > %s
            ORDER BY t.asset_id, t.variant, t.snapshot_date;
            """,
            (start_date, MIN_MARKET_PRICE),
        )
        return cur.fetchall()


def choose_variant(variants: dict, target_date: date):
    for variant in PREFERRED_VARIANTS:
        rows = variants.get(variant, [])
        if any(d == target_date for d, _ in rows):
            return variant, rows
    for variant in PREFERRED_VARIANTS:
        rows = variants.get(variant, [])
        if rows:
            return variant, rows
    return None, []


def compute_ses(prices: list[tuple], alpha: float):
    if not prices:
        return 0.0, 0.0
    s = float(prices[0][1])
    for _, price in prices[1:]:
        s = (alpha * float(price)) + ((1 - alpha) * s)
    return s, float(prices[-1][1])


def main():
    conn = connect()
    try:
        start_date = date.today() - timedelta(days=LOOKBACK_DAYS)
        rows = fetch_price_history(conn, start_date)
        if not rows:
            print("No price history found for the lookback window.")
            return

        asset_variants = defaultdict(lambda: defaultdict(list))
        for snap_date, asset_id, variant, market in rows:
            asset_variants[asset_id][variant].append((snap_date, market))

        sample_asset = max(
            asset_variants.items(),
            key=lambda kv: sum(len(v) for v in kv[1].values()),
        )[0]

        variant, price_rows = choose_variant(asset_variants[sample_asset], date.today())
        price_rows.sort(key=lambda r: r[0])
        if not price_rows:
            print("No price rows found for sample asset.")
            return

        smooth_price, market_price = compute_ses(price_rows, DEFAULT_ALPHA)
        gap = smooth_price - market_price
        gap_pct = gap / market_price if market_price else 0

        print("Sample asset:")
        print(f"  asset_id: {sample_asset}")
        print(f"  variant: {variant}")
        print(f"  last_date: {price_rows[-1][0]}")
        print("Inputs:")
        print(f"  alpha: {DEFAULT_ALPHA}")
        print(f"  lookback_days: {LOOKBACK_DAYS}")
        print(f"  min_market_price: {MIN_MARKET_PRICE}")
        print(f"  price_points: {len(price_rows)}")
        show_n = min(10, len(price_rows))
        if show_n:
            print(f"  first_{show_n}_points:")
            for snap_date, price in price_rows[:show_n]:
                print(f"    {snap_date} -> {float(price):.6f}")
        if len(price_rows) > show_n:
            print(f"  last_{show_n}_points:")
            for snap_date, price in price_rows[-show_n:]:
                print(f"    {snap_date} -> {float(price):.6f}")
        print("Computed values:")
        print(f"  market_price: {market_price:.4f}")
        print(f"  smooth_price: {smooth_price:.4f}")
        print(f"  gap: {gap:.6f}")
        print(f"  gap_pct: {gap_pct:.6f}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
