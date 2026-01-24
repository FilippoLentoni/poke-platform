import os
from datetime import date
from typing import Dict, Tuple

import boto3
import pandas as pd
import psycopg2


DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "poke")
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]

S3_BUCKET = os.environ["S3_BUCKET"]
S3_PREFIX = os.environ.get("S3_PREFIX", "snapshots").strip("/")
EXPORT_DATE = os.environ.get("EXPORT_DATE")


TABLES: Dict[str, str] = {
    "card_metadata": "snapshot_date",
    "tcgplayer_price_snapshot": "snapshot_date",
    "cardmarket_price_snapshot": "snapshot_date",
    "valuation_daily": "val_date",
}


def connect():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=10,
    )


def export_table(
    conn,
    s3_client,
    table: str,
    date_col: str,
    export_date: str,
) -> None:
    query = f"SELECT * FROM {table} WHERE {date_col} = %s;"
    df = pd.read_sql_query(query, conn, params=(export_date,))
    if df.empty:
        print(f"{table}: no rows for {export_date}")
        return

    filename = f"/tmp/{table}-{export_date}.parquet"
    df.to_parquet(filename, index=False)

    prefix = f"{S3_PREFIX}/" if S3_PREFIX else ""
    key = f"{prefix}table={table}/snapshot_date={export_date}/{table}-{export_date}.parquet"
    s3_client.upload_file(filename, S3_BUCKET, key)
    print(f"{table}: wrote s3://{S3_BUCKET}/{key} rows={len(df)}")


def main() -> None:
    export_date = EXPORT_DATE or date.today().isoformat()
    print(f"Starting export for {export_date}")
    s3_client = boto3.client("s3")

    conn = connect()
    try:
        for table, date_col in TABLES.items():
            export_table(conn, s3_client, table, date_col, export_date)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
