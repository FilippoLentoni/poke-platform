import json
import os
from typing import Dict

import boto3
import pandas as pd
import psycopg2

DEFAULT_REGION = os.environ.get("REGION", "us-east-2")
DEFAULT_SECRET_ARN = os.environ.get(
    "SECRET_ARN",
    "arn:aws:secretsmanager:us-east-2:878817878019:secret:PokePlatformStackPostgresSe-uD7oKVjyUmYi-NFBVMe",
)


def fetch_db_secret(region: str = DEFAULT_REGION, secret_arn: str = DEFAULT_SECRET_ARN) -> Dict[str, str]:
    """Load DB connection details from Secrets Manager."""
    client = boto3.client("secretsmanager", region_name=region)
    resp = client.get_secret_value(SecretId=secret_arn)
    secret_str = resp.get("SecretString") or "{}"
    return json.loads(secret_str)


def connect(region: str = DEFAULT_REGION, secret_arn: str = DEFAULT_SECRET_ARN):
    """Create a psycopg2 connection using Secrets Manager credentials."""
    secret = fetch_db_secret(region=region, secret_arn=secret_arn)
    return psycopg2.connect(
        host=secret.get("host"),
        port=int(secret.get("port", 5432)),
        dbname=secret.get("dbname", "poke"),
        user=secret.get("username"),
        password=secret.get("password"),
        connect_timeout=10,
    )


def read_sql(query: str, region: str = DEFAULT_REGION, secret_arn: str = DEFAULT_SECRET_ARN) -> pd.DataFrame:
    """Run a SQL query and return a DataFrame."""
    with connect(region=region, secret_arn=secret_arn) as conn:
        return pd.read_sql(query, conn)
