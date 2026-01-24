import io
import json
import os
import subprocess
from typing import Dict

import boto3
import pandas as pd
import psycopg2

DEFAULT_REGION = os.environ.get("REGION", "us-east-2")
DEFAULT_SECRET_ARN = os.environ.get(
    "SECRET_ARN",
    "arn:aws:secretsmanager:us-east-2:878817878019:secret:PokePlatformStackPostgresSe-uD7oKVjyUmYi-NFBVMe",
)
DEFAULT_STACK = os.environ.get("STACK", "PokePlatformStack")
DEFAULT_CONTAINER = os.environ.get("CONTAINER", "ApiContainer")


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

def read_sql_via_ecs_exec(
    query: str,
    region: str = DEFAULT_REGION,
    stack: str = DEFAULT_STACK,
    container: str = DEFAULT_CONTAINER,
) -> pd.DataFrame:
    """Run a SQL query via ECS Exec and return a DataFrame (CSV output)."""
    script_path = os.path.join(os.path.dirname(__file__), "run_db_query.sh")
    cmd = [
        "bash",
        script_path,
        "--quiet",
        "--csv",
        "-q",
        query,
    ]
    env = os.environ.copy()
    env["REGION"] = region
    env["STACK"] = stack
    env["CONTAINER"] = container
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            "ECS exec query failed. stderr:\n"
            f"{result.stderr.strip()}"
        )
    output = result.stdout.strip()
    if not output:
        raise RuntimeError("ECS exec query returned no output.")
    try:
        lines = [
            line
            for line in output.splitlines()
            if line.strip()
            and not line.startswith("Starting session with SessionId:")
            and not line.startswith("The Session Manager plugin")
            and not line.startswith("Cannot perform start session:")
        ]
        cleaned = "\n".join(lines)
        return pd.read_csv(io.StringIO(cleaned))
    except Exception as exc:
        raise RuntimeError(
            "Failed to parse CSV output from ECS exec query."
        ) from exc


def read_sql(
    query: str,
    region: str = DEFAULT_REGION,
    secret_arn: str = DEFAULT_SECRET_ARN,
    stack: str = DEFAULT_STACK,
    container: str = DEFAULT_CONTAINER,
    use_ecs_exec: bool = False,
) -> pd.DataFrame:
    """Run a SQL query and return a DataFrame."""
    if use_ecs_exec or os.environ.get("USE_ECS_EXEC") == "1":
        return read_sql_via_ecs_exec(query, region=region, stack=stack, container=container)
    try:
        with connect(region=region, secret_arn=secret_arn) as conn:
            return pd.read_sql(query, conn)
    except psycopg2.OperationalError as exc:
        if "timeout expired" in str(exc) or "could not connect" in str(exc):
            return read_sql_via_ecs_exec(query, region=region, stack=stack, container=container)
        raise
