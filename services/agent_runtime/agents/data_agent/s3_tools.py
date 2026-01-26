from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

import boto3


@dataclass(frozen=True)
class S3PriceConfig:
    bucket: str
    prefix: str = ""
    region: str = "us-east-1"


def load_s3_price_config_from_env() -> Optional[S3PriceConfig]:
    bucket = os.getenv("S3_PRICE_BUCKET")
    if not bucket:
        return None
    return S3PriceConfig(
        bucket=bucket,
        prefix=os.getenv("S3_PRICE_PREFIX", ""),
        region=os.getenv("AWS_REGION", "us-east-1"),
    )


def fetch_price_history_from_s3_jsonl(
    cfg: S3PriceConfig,
    card_name: str,
    market: str = "cardmarket",
    limit: int = 365,
) -> List[Dict[str, Any]]:
    """
    Minimal “Step 0” implementation:
    - Assumes a JSONL object per card:
        s3://{bucket}/{prefix}/{market}/{card_name}.jsonl
      with lines like:
        {"date":"2026-01-01","price":12.3,"currency":"EUR"}

    Replace with your preferred format later (Parquet + Athena, Iceberg, etc).
    """
    s3 = boto3.client("s3", region_name=cfg.region)
    key = f"{cfg.prefix.rstrip('/')}/{market}/{card_name}.jsonl".lstrip("/")

    try:
        obj = s3.get_object(Bucket=cfg.bucket, Key=key)
    except s3.exceptions.NoSuchKey:
        return []

    body = obj["Body"].read().decode("utf-8").splitlines()
    out: List[Dict[str, Any]] = []
    for line in body[:limit]:
        line = line.strip()
        if not line:
            continue
        import json

        rec = json.loads(line)
        rec["market"] = market
        out.append(rec)
    return out
